package onboarding

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/curriculum"
)

// SyncReport is what a curriculum sync did, for the operator to review. Name
// differences are reported, never overwritten: a school that renamed a
// capability did so on purpose, and the sync must not silently undo it.
type SyncReport struct {
	Colegio          string
	TenantID         uuid.UUID
	Grados           int
	Competencias     int
	Capacidades      int
	Estandares       int
	Desempenos       int
	NivelesEsperados int
	Renamed          []string
}

func (r *SyncReport) String() string {
	var b strings.Builder
	fmt.Fprintf(&b, "Colegio:        %s (%s)\n", r.Colegio, r.TenantID)
	fmt.Fprintf(&b, "Revisado:       %d competencias del catálogo\n", r.Competencias)
	fmt.Fprintf(&b, "Insertado:      %d capacidades, %d estándares, %d desempeños y %d niveles esperados\n", r.Capacidades, r.Estandares, r.Desempenos, r.NivelesEsperados)
	fmt.Fprintf(&b, "Grados:         %d con nivel o ciclo actualizado\n", r.Grados)
	if len(r.Renamed) == 0 {
		fmt.Fprintf(&b, "Nombres:        sin diferencias con el catálogo\n")
	} else {
		fmt.Fprintf(&b, "Nombres distintos (NO se cambiaron; revisa y decide):\n")
		for _, line := range r.Renamed {
			fmt.Fprintf(&b, "  - %s\n", line)
		}
	}
	return b.String()
}

// SyncCurriculum brings an already-onboarded school's curriculum up to date
// with the catalog, inside tx (the caller owns the transaction, exactly like
// Load). It matches competencies and capabilities by code, inserts what is
// missing, sets grade_levels.cycle from the explicit gradeMap, and reports
// name differences without changing them. A second run changes nothing.
//
// Nothing is inferred: the grade → grado_cneb map is declared by the caller,
// never guessed from ordinals.
func SyncCurriculum(ctx context.Context, tx pgx.Tx, cat *curriculum.Catalog, modularCode string, gradeMap map[string]string) (*SyncReport, error) {
	if len(gradeMap) == 0 {
		return nil, fmt.Errorf("sync: falta el mapeo grado → grado_cneb")
	}
	var tenant uuid.UUID
	var colegio string
	if err := tx.QueryRow(ctx, `
		select id, name from tenants
		 where modular_code = $1 and deleted_at is null`, modularCode).Scan(&tenant, &colegio); err != nil {
		return nil, fmt.Errorf("colegio %s: %w", modularCode, err)
	}
	s := &syncer{
		ctx:    ctx,
		tx:     tx,
		cat:    cat,
		mod:    modularCode,
		tenant: tenant,
		report: &SyncReport{Colegio: colegio, TenantID: tenant},
		grades: map[string]schoolGrade{},
	}

	if err := s.setGradeCycles(gradeMap); err != nil {
		return nil, err
	}
	if err := s.syncCompetencies(); err != nil {
		return nil, err
	}
	if err := s.syncMappings(); err != nil {
		return nil, err
	}
	sort.Strings(s.report.Renamed)
	return s.report, nil
}

type syncer struct {
	ctx    context.Context
	tx     pgx.Tx
	cat    *curriculum.Catalog
	mod    string
	tenant uuid.UUID
	report *SyncReport
	// grades maps the school's grade code to its catalog grade and row id.
	grades map[string]schoolGrade
}

// setGradeCycles sets grade_levels.stage and cycle from the explicit
// grado → grado_cneb map. Only the grades the map names are touched; a grade
// the school has but the map omits keeps whatever it had, and is reported so
// the operator notices.
func (s *syncer) setGradeCycles(gradeMap map[string]string) error {
	for codigo, cneb := range gradeMap {
		cg := s.cat.Grado[cneb]
		var id uuid.UUID
		var stage string
		var cycle *string
		err := s.tx.QueryRow(s.ctx, `
			select id, stage, cycle from grade_levels
			 where tenant_id = $1 and code = $2 and deleted_at is null`,
			s.tenant, codigo).Scan(&id, &stage, &cycle)
		if errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("el colegio no tiene el grado %q", codigo)
		}
		if err != nil {
			return fmt.Errorf("grado %s: %w", codigo, err)
		}
		s.grades[codigo] = schoolGrade{cneb: cg, level: id}
		// Only write when something changes, so a second run really changes
		// nothing (not even updated_at).
		if stage == cg.Nivel && cycle != nil && *cycle == cg.Ciclo {
			continue
		}
		if _, err := s.tx.Exec(s.ctx, `
			update grade_levels set stage = $3, cycle = $4
			 where tenant_id = $1 and id = $2`,
			s.tenant, id, cg.Nivel, cg.Ciclo); err != nil {
			return fmt.Errorf("grado %s: %w", codigo, err)
		}
		s.report.Grados++
	}
	return nil
}

// syncCompetencies walks every competency the school already has, matching by
// code, and inserts what the catalog has and the school lacks: capabilities,
// standards and the performances of the mapped grades. Competencies the
// school does not have are not created: which areas a school uses is its
// decision, and the sync is not the place to make it.
func (s *syncer) syncCompetencies() error {
	rows, err := s.tx.Query(s.ctx, `
		select c.id, c.code, c.name, c.kind, coalesce(sub.code, '')
		  from competencies c
		  left join subjects sub on sub.id = c.subject_id and sub.tenant_id = c.tenant_id
		 where c.tenant_id = $1 and c.deleted_at is null
		 order by c.code`, s.tenant)
	if err != nil {
		return err
	}
	defer rows.Close()
	type existing struct {
		id, code, name, kind, subject string
	}
	var comps []existing
	for rows.Next() {
		var c existing
		if err := rows.Scan(&c.id, &c.code, &c.name, &c.kind, &c.subject); err != nil {
			return err
		}
		comps = append(comps, c)
	}
	if err := rows.Err(); err != nil {
		return err
	}

	for _, c := range comps {
		comp, ok := s.cat.CompetenciaByCode(c.code)
		if !ok {
			// A school's own competency (kind adicional_*) is not in the
			// catalog and is none of the catalog's business.
			continue
		}
		if comp.Nombre != c.name {
			s.report.Renamed = append(s.report.Renamed,
				fmt.Sprintf("competencia %s: el colegio dice %q y el catálogo %q", c.code, c.name, comp.Nombre))
		}
		s.report.Competencias++
		if err := s.syncCapabilities(c.code, comp); err != nil {
			return err
		}
		if err := s.syncStandards(c.code, comp); err != nil {
			return err
		}
		if err := s.syncPerformances(c.code, comp); err != nil {
			return err
		}
	}
	return nil
}

// syncCapabilities inserts the capabilities the catalog defines and the
// school lacks, matched by code, reporting name differences.
func (s *syncer) syncCapabilities(codigo string, comp curriculum.Competencia) error {
	compID := ID("competency", s.mod, codigo)
	for k, cap := range comp.Capacidades {
		capCode := curriculum.CapabilityCode(codigo, cap.Numero)
		capID := ID("capability", s.mod, capCode)
		var name string
		err := s.tx.QueryRow(s.ctx, `
			select name from capabilities
			 where tenant_id = $1 and id = $2 and deleted_at is null`,
			s.tenant, capID).Scan(&name)
		switch err {
		case nil:
			if name != cap.Nombre {
				s.report.Renamed = append(s.report.Renamed,
					fmt.Sprintf("capacidad %s: el colegio dice %q y el catálogo %q", capCode, name, cap.Nombre))
			}
			continue
		default:
			return fmt.Errorf("capacidad %s: %w", capCode, err)
		case pgx.ErrNoRows:
			// Insert below.
		}
		if err := s.exec(`
			insert into capabilities (id, tenant_id, competency_id, code, name, sort_order)
			values ($1, $2, $3, $4, $5, $6)`,
			capID, s.tenant, compID, capCode, cap.Nombre, k+1); err != nil {
			return fmt.Errorf("capacidad %s: %w", capCode, err)
		}
		s.report.Capacidades++
	}
	return nil
}

// syncStandards inserts the learning standards the catalog has and the school
// lacks, matched by (competency, level).
func (s *syncer) syncStandards(codigo string, comp curriculum.Competencia) error {
	compID := ID("competency", s.mod, codigo)
	for _, e := range comp.Estandares {
		stdID := ID("standard", s.mod, fmt.Sprintf("%s:%d", codigo, e.Nivel))
		tag, err := s.tx.Exec(s.ctx, `
			insert into learning_standards (id, tenant_id, competency_id, level, official_text)
			values ($1, $2, $3, $4, $5)
			on conflict (tenant_id, competency_id, level) where deleted_at is null do nothing`,
			stdID, s.tenant, compID, e.Nivel, e.Texto)
		if err != nil {
			return fmt.Errorf("estándar %s nivel %d: %w", codigo, e.Nivel, err)
		}
		if tag.RowsAffected() == 1 {
			s.report.Estandares++
		}
	}
	return nil
}

// syncPerformances inserts the grade-level performances of the mapped grades
// that the school lacks, matched by (competency, grade, order), with the
// derived stance and expected level.
func (s *syncer) syncPerformances(codigo string, comp curriculum.Competencia) error {
	compID := ID("competency", s.mod, codigo)
	for _, g := range s.grades {
		enProceso := s.cat.EnProceso(g.cneb.Codigo)
		expected, ok := s.cat.ExpectedLevel(curriculum.DefaultModality, g.cneb.Ciclo)
		if !ok {
			return fmt.Errorf("ciclo %s: el catálogo no declara el nivel esperado para la modalidad %s", g.cneb.Ciclo, curriculum.DefaultModality)
		}
		for _, d := range comp.Desempenos {
			if d.Grado != g.cneb.Codigo {
				continue
			}
			var suggested *uuid.UUID
			if d.CapacidadSugerida != nil {
				id := ID("capability", s.mod, curriculum.CapabilityCode(codigo, *d.CapacidadSugerida))
				suggested = &id
			}
			perfID := ID("performance", s.mod, codigo+":"+g.cneb.Codigo+":"+fmt.Sprint(d.Orden))
			tag, err := s.tx.Exec(s.ctx, `
				insert into grade_level_performances (id, tenant_id, competency_id, grade_level_id,
				                                      sort_order, official_text, en_proceso,
				                                      expected_standard_level, suggested_capability_id)
				values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
				on conflict (tenant_id, competency_id, grade_level_id, sort_order) where deleted_at is null do nothing`,
				perfID, s.tenant, compID, g.level, d.Orden, d.Texto, enProceso, expected, suggested)
			if err != nil {
				return fmt.Errorf("desempeño %s %s #%d: %w", codigo, g.cneb.Codigo, d.Orden, err)
			}
			if tag.RowsAffected() == 1 {
				s.report.Desempenos++
			}
		}
	}
	return nil
}

// syncMappings inserts the (modality, cycle) → expected level rows for the
// cycles of the mapped grades that the school lacks.
func (s *syncer) syncMappings() error {
	seen := map[string]bool{}
	for _, g := range s.grades {
		if seen[g.cneb.Ciclo] {
			continue
		}
		seen[g.cneb.Ciclo] = true
		level, ok := s.cat.ExpectedLevel(curriculum.DefaultModality, g.cneb.Ciclo)
		if !ok {
			return fmt.Errorf("ciclo %s: el catálogo no declara el nivel esperado para la modalidad %s", g.cneb.Ciclo, curriculum.DefaultModality)
		}
		tag, err := s.tx.Exec(s.ctx, `
			insert into standard_level_mappings (id, tenant_id, modality, cycle, expected_level)
			values ($1, $2, $3, $4, $5)
			on conflict (tenant_id, modality, cycle) where deleted_at is null do nothing`,
			ID("standard_level_mapping", s.mod, curriculum.DefaultModality+":"+g.cneb.Ciclo),
			s.tenant, curriculum.DefaultModality, g.cneb.Ciclo, level)
		if err != nil {
			return fmt.Errorf("nivel esperado del ciclo %s: %w", g.cneb.Ciclo, err)
		}
		if tag.RowsAffected() == 1 {
			s.report.NivelesEsperados++
		}
	}
	return nil
}

func (s *syncer) exec(sql string, args ...any) error {
	_, err := s.tx.Exec(s.ctx, sql, args...)
	return err
}
