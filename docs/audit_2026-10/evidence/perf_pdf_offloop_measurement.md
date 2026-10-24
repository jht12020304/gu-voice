# PDF export: event-loop blocking (local, dev config, Mac)

Method: start a GET /reports/{id}/pdf in the background, 300 ms later time GET /api/v1/health on the same uvicorn worker (single worker, port 18000, smoothness DB).

| Trial | Before fix (sync write_pdf in async def) | After fix (asyncio.to_thread + render lock) |
|---|---|---|
| health alone | 0.9–1.0 ms | 0.9–1.0 ms |
| health during PDF #1 | 956 ms | 1.6 ms |
| health during PDF #2 | – | 142 ms |
| health during PDF #3 | – | 112 ms |
| PDF itself | 1,267 ms | 1,242–1,518 ms |
| 3 concurrent PDFs wall | (serialized by blocked loop) | 3.87 s (serialized by lock; loop stays responsive) |

Residual 100–140 ms is GIL contention from the CPU-bound render thread (pure-Python layout in WeasyPrint); eliminating it needs a process pool (noted as the upgrade path in the code comment).
Memory: first render still retains ~550 MB RSS (font parsing); unchanged by this fix — tracked separately.
