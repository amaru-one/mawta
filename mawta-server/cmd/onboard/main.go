// Command onboard installs a new school from one onboarding JSON file (see
// seed/onboarding/plantilla.json and docs/instalar-un-colegio.md). Everything
// goes in one transaction: the school is fully created or not at all.
//
//	onboard -file colegio.json            # load
//	onboard -file colegio.json -dry-run   # validate and roll back
//	onboard -file - < colegio.json        # read from stdin (the droplet path)
//
// The curriculum tree (competencies, capabilities, standards, performances)
// is not in the file: it is copied from the CNEB catalog embedded in this
// binary (mawta-server/curriculum/cneb).
//
// For a school that already exists, the sync brings its curriculum up to date
// with the catalog, in one transaction and with the same dry-run:
//
//	onboard -sync -modular 0723519 -grado 1S=1S [-dry-run]
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/jackc/pgx/v5"

	"mawta-server/curriculum"
	"mawta-server/internal/config"
	"mawta-server/internal/db"
	"mawta-server/internal/onboarding"
)

// errRollback ends a dry run: WithSystemTx rolls back on any error.
var errRollback = errors.New("dry run")

func main() {
	if err := run(); err != nil {
		var list onboarding.Errors
		if errors.As(err, &list) {
			fmt.Fprintf(os.Stderr, "El archivo tiene %d problema(s). No se cargó nada.\n\n", len(list))
			for _, e := range list {
				fmt.Fprintln(os.Stderr, "  - "+e)
			}
		} else {
			fmt.Fprintln(os.Stderr, "onboard:", err)
		}
		os.Exit(1)
	}
}

func run() error {
	file := flag.String("file", "", "archivo JSON del colegio, o - para leerlo de stdin; obligatorio")
	dryRun := flag.Bool("dry-run", false, "valida y ejecuta todo en una transacción que luego se deshace")
	sync := flag.Bool("sync", false, "sincroniza el currículo CNEB de un colegio ya instalado (requiere -modular)")
	modular := flag.String("modular", "", "código modular del colegio a sincronizar (con -sync)")
	var grados []string
	flag.Func("grado", "con -sync: <grado del colegio>=<grado CNEB>, por ejemplo 1S=1S; se repite por cada grado", func(v string) error {
		grados = append(grados, v)
		return nil
	})
	flag.Parse()
	if flag.NArg() > 0 {
		return fmt.Errorf("argumentos inesperados: %s (los grados van con -grado)", strings.Join(flag.Args(), " "))
	}

	// The catalog is an input, not a runtime option: a binary carrying a
	// broken catalog must refuse to do anything at all.
	cat, err := curriculum.Load()
	if err != nil {
		return err
	}

	if *sync {
		return runSync(cat, *modular, grados, *dryRun)
	}

	if *file == "" {
		return errors.New("falta -file (o -sync -modular <código>)")
	}

	var in io.Reader = os.Stdin
	if *file != "-" {
		f, err := os.Open(*file)
		if err != nil {
			return err
		}
		defer f.Close()
		in = f
	}
	spec, err := onboarding.Decode(in)
	if err != nil {
		return err
	}
	// Validate before connecting, so a file full of typos is reported even
	// when no database is reachable.
	if err := onboarding.ValidateWithCatalog(spec, cat); err != nil {
		return err
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	// Like cmd/useradd: the first users/memberships rows of a tenant can only
	// be written by a connection that bypasses row security.
	if cfg.AdminDatabaseURL == "" {
		return errors.New("ADMIN_DATABASE_URL es obligatoria (una conexión de superusuario; mawta_app no puede crear un colegio)")
	}
	ctx := context.Background()
	database, err := db.Open(ctx, cfg.AdminDatabaseURL)
	if err != nil {
		return err
	}
	defer database.Close()

	var summary *onboarding.Summary
	err = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
		summary, err = onboarding.Load(ctx, tx, spec, cat, cfg.BcryptCost)
		if err != nil {
			return err
		}
		if *dryRun {
			return errRollback
		}
		return nil
	})
	if err != nil && !errors.Is(err, errRollback) {
		return err
	}

	fmt.Print(summary)
	if *dryRun {
		fmt.Println("\nPRUEBA (-dry-run): todo es válido, pero no se guardó nada.")
	} else {
		fmt.Println("\nListo. Entrega a cada docente su usuario y la clave del archivo.")
	}
	return nil
}

// runSync brings an already-onboarded school's curriculum up to date with the
// catalog: it inserts the capabilities, standards, performances and
// (modality, cycle) mappings that are missing, sets grade_levels.cycle from
// the explicit grado → grado_cneb map, and reports name differences instead
// of overwriting them. It is idempotent: a second run changes nothing.
func runSync(cat *curriculum.Catalog, modular string, args []string, dryRun bool) error {
	if modular == "" {
		return errors.New("-sync requiere -modular <código modular del colegio>")
	}
	if len(args) == 0 {
		return errors.New("-sync requiere al menos un -grado <grado>=<grado_cneb>, por ejemplo -grado 1S=1S")
	}
	gradeMap := map[string]string{}
	for _, a := range args {
		codigo, cneb, ok := strings.Cut(a, "=")
		if !ok || codigo == "" || cneb == "" {
			return fmt.Errorf("-grado %q: debe tener la forma <grado>=<grado_cneb>, por ejemplo 1S=1S", a)
		}
		if _, ok := cat.Grado[cneb]; !ok {
			return fmt.Errorf("-grado %q: %q no es un grado del catálogo CNEB; los grados son: %s", a, cneb, catGradeList(cat))
		}
		if prev, dup := gradeMap[codigo]; dup {
			return fmt.Errorf("-grado: el grado %q aparece dos veces (=%s y =%s)", codigo, prev, cneb)
		}
		gradeMap[codigo] = cneb
	}

	cfg, err := config.Load()
	if err != nil {
		return err
	}
	if cfg.AdminDatabaseURL == "" {
		return errors.New("ADMIN_DATABASE_URL es obligatoria (una conexión de superusuario; mawta_app no puede escribir el currículo)")
	}
	ctx := context.Background()
	database, err := db.Open(ctx, cfg.AdminDatabaseURL)
	if err != nil {
		return err
	}
	defer database.Close()

	var report *onboarding.SyncReport
	err = database.WithSystemTx(ctx, func(tx pgx.Tx) error {
		report, err = onboarding.SyncCurriculum(ctx, tx, cat, modular, gradeMap)
		if err != nil {
			return err
		}
		if dryRun {
			return errRollback
		}
		return nil
	})
	if err != nil && !errors.Is(err, errRollback) {
		return err
	}

	fmt.Print(report)
	if dryRun {
		fmt.Println("\nPRUEBA (-dry-run): nada se guardó.")
	}
	return nil
}

func catGradeList(cat *curriculum.Catalog) string {
	codes := make([]string, 0, len(cat.Grados))
	for _, g := range cat.Grados {
		codes = append(codes, g.Codigo)
	}
	return strings.Join(codes, ", ")
}
