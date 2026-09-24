// Command onboard installs a new school from one onboarding JSON file (see
// seed/onboarding/plantilla.json and docs/instalar-un-colegio.md). Everything
// goes in one transaction: the school is fully created or not at all.
//
//	onboard -file colegio.json            # load
//	onboard -file colegio.json -dry-run   # validate and roll back
//	onboard -file - < colegio.json        # read from stdin (the droplet path)
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/jackc/pgx/v5"

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
	flag.Parse()
	if *file == "" {
		return errors.New("falta -file")
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
	if err := onboarding.Validate(spec); err != nil {
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
		summary, err = onboarding.Load(ctx, tx, spec, cfg.BcryptCost)
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
