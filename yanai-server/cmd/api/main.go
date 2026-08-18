// Command api starts the Yanai HTTP server and, when enabled, the
// in-process background job worker.
package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"yanai-server/internal/config"
	"yanai-server/internal/db"
	"yanai-server/internal/httpapi"
	"yanai-server/internal/worker"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	cfg, err := config.Load()
	if err != nil {
		logger.Error("config", "error", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	database, err := db.Open(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("db open", "error", err)
		os.Exit(1)
	}
	defer database.Close()

	if err := os.MkdirAll(cfg.StorageDir, 0o755); err != nil {
		logger.Error("storage dir", "error", err)
		os.Exit(1)
	}

	api := httpapi.New(database, cfg, logger)

	server := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           api.Router(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	var workerWG sync.WaitGroup
	var workerCancel context.CancelFunc
	if cfg.WorkerEnabled {
		var workerCtx context.Context
		workerCtx, workerCancel = context.WithCancel(context.Background())
		workerWG.Add(1)
		go func() {
			defer workerWG.Done()
			worker.Run(workerCtx, database, cfg, logger)
		}()
		logger.Info("worker started", "concurrency", cfg.WorkerConcurrency)
	}

	go func() {
		logger.Info("http server listening", "addr", cfg.HTTPAddr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("http server", "error", err)
			stop()
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("http shutdown", "error", err)
	}

	if workerCancel != nil {
		workerCancel()
		workerWG.Wait()
	}
}
