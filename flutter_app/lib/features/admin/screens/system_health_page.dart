import 'package:flutter/material.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/admin_api.dart';

// Port of frontend/src/screens/admin/SystemHealthPage.tsx.
// getSystemHealth() returns a Map whose shapes vary (a field may be a plain
// status string OR a nested {status, ...} object), so every read goes through
// _statusOf() which coerces defensively. Status -> traffic-light colors via
// AppTokens (green/amber/red). Refresh button re-fetches.
class SystemHealthPage extends StatefulWidget {
  const SystemHealthPage({super.key});

  @override
  State<SystemHealthPage> createState() => _SystemHealthPageState();
}

class _SystemHealthPageState extends State<SystemHealthPage> {
  final _api = AdminApi();

  Map _health = const {};
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    Future.microtask(_load);
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final res = await _api.getSystemHealth();
      if (!mounted) return;
      setState(() {
        _health = res;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = t('admin.systemHealth.loadError');
        _loading = false;
      });
    }
  }

  // Coerce a health field (String | Map{status} | anything) into a status token.
  String _statusOf(Object? v) {
    if (v == null) return 'unknown';
    if (v is String) return v.isEmpty ? 'unknown' : v;
    if (v is Map) {
      final s = v['status'] ?? v['state'] ?? v['health'] ?? v['connected'];
      if (s is bool) return s ? 'ok' : 'error';
      if (s != null && s.toString().isNotEmpty) return s.toString();
      return 'unknown';
    }
    if (v is bool) return v ? 'ok' : 'error';
    return v.toString();
  }

  bool _isOk(String s) {
    final low = s.toLowerCase();
    return low == 'ok' || low == 'healthy' || low == 'up' || low == 'connected' || low == 'ready' || low == 'online' || low == 'true';
  }

  bool _isBad(String s) {
    final low = s.toLowerCase();
    return low == 'error' || low == 'down' || low == 'unhealthy' || low == 'disconnected' || low == 'fail' || low == 'failed' || low == 'false' || low == 'offline';
  }

  Color _statusColor(String s, AppTokens tk) {
    if (_isOk(s)) return tk.alertSuccess;
    if (_isBad(s)) return tk.alertCritical;
    return tk.alertMedium; // unknown / degraded -> amber
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(t('admin.systemHealth.title')),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: t('admin.systemHealth.refresh'),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      body: _body(context),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading && _health.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 12),
          Text(t('admin.systemHealth.loading')),
        ]),
      );
    }
    if (_error != null && _health.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error!, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          FilledButton.tonal(onPressed: _load, child: Text(t('admin.systemHealth.refresh'))),
        ]),
      );
    }

    final tk = Theme.of(context).extension<AppTokens>()!;
    final status = _statusOf(_health['status']);
    final database = _statusOf(_health['database']);
    final redis = _statusOf(_health['redis']);
    final openai = _statusOf(_health['openai']);
    final version = _health['version']?.toString() ?? 'unknown';
    final timestamp = _health['timestamp']?.toString();

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(t('admin.systemHealth.subtitle'), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _statusCard(context, tk, Icons.dns, t('admin.systemHealth.metrics.apiStatus'), status, colored: true),
              _statusCard(context, tk, Icons.storage, t('admin.systemHealth.metrics.database'), database, colored: true),
              _statusCard(context, tk, Icons.memory, t('admin.systemHealth.metrics.redis'), redis, colored: true),
              _statusCard(context, tk, Icons.auto_awesome, t('admin.systemHealth.metrics.openai'), openai, colored: true),
              _statusCard(context, tk, Icons.public, t('admin.systemHealth.metrics.version'), version, colored: false),
            ],
          ),
          const SizedBox(height: 24),
          _eventsCard(context, tk, status, timestamp),
          const SizedBox(height: 16),
          _dependencyCard(context, tk, openai: openai, database: database, redis: redis),
        ],
      ),
    );
  }

  Widget _statusCard(BuildContext context, AppTokens tk, IconData icon, String label, String value, {required bool colored}) {
    final color = colored ? _statusColor(value, tk) : Theme.of(context).colorScheme.onSurface;
    return SizedBox(
      width: 260,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(icon, size: 20, color: Theme.of(context).colorScheme.onSurfaceVariant),
                const SizedBox(width: 8),
                Expanded(child: Text(label, style: Theme.of(context).textTheme.labelMedium)),
              ]),
              const SizedBox(height: 12),
              Row(children: [
                if (colored) ...[
                  Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: Text(
                    value,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700, color: color),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ]),
            ],
          ),
        ),
      ),
    );
  }

  Widget _eventsCard(BuildContext context, AppTokens tk, String status, String? timestamp) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('admin.systemHealth.eventsTitle'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 16),
            _eventRow(
              context,
              _statusColor(status, tk),
              t('admin.systemHealth.backendStatus'),
              status,
            ),
            const SizedBox(height: 12),
            _eventRow(
              context,
              Theme.of(context).colorScheme.primary,
              t('admin.systemHealth.lastHealthCheck'),
              timestamp ?? t('admin.systemHealth.notProvided'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _eventRow(BuildContext context, Color color, String label, String value) {
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(Icons.schedule, size: 18, color: color),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
          Text(value, style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
    ]);
  }

  Widget _dependencyCard(BuildContext context, AppTokens tk, {required String openai, required String database, required String redis}) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(t('admin.systemHealth.dependencyTitle'), style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(t('admin.systemHealth.dependencyNote'), style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            _depBar(context, tk, t('admin.systemHealth.metrics.openai'), openai),
            const SizedBox(height: 12),
            _depBar(context, tk, t('admin.systemHealth.metrics.database'), database),
            const SizedBox(height: 12),
            _depBar(context, tk, t('admin.systemHealth.metrics.redis'), redis),
          ],
        ),
      ),
    );
  }

  Widget _depBar(BuildContext context, AppTokens tk, String label, String value) {
    final color = _statusColor(value, tk);
    final fraction = _isOk(value) ? 1.0 : 0.4;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(label, style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
          Text(value, style: Theme.of(context).textTheme.bodySmall),
        ]),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: fraction,
            minHeight: 8,
            backgroundColor: color.withValues(alpha: 0.15),
            valueColor: AlwaysStoppedAnimation(color),
          ),
        ),
      ],
    );
  }
}
