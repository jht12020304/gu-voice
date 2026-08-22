import 'package:flutter/material.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/admin_api.dart';
import '../../../shared/widgets/ui_kit.dart';
import '../../../shared/widgets/dashboard_back_button.dart';

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

  // ok 對應 statusCompleted 而非 alertSuccess：與 alert_list_page 的
  // acknowledged 用同一顆語意綠，全站「正常/已完成」共用一種綠色語彙。
  Color _statusColor(String s, AppTokens tk) {
    if (_isOk(s)) return tk.statusCompleted;
    if (_isBad(s)) return tk.alertCritical;
    return tk.alertMedium; // unknown / degraded -> amber
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: const DashboardBackButton(),
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
      return const SkeletonList();
    }
    if (_error != null && _health.isEmpty) {
      return ErrorState(
        message: _error!,
        retryLabel: t('admin.systemHealth.refresh'),
        onRetry: _load,
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
          _ServiceStatusGroup(tk: tk, rows: [
            _ServiceRow(Icons.dns, t('admin.systemHealth.metrics.apiStatus'), status, _statusColor(status, tk)),
            _ServiceRow(Icons.storage, t('admin.systemHealth.metrics.database'), database, _statusColor(database, tk)),
            _ServiceRow(Icons.memory, t('admin.systemHealth.metrics.redis'), redis, _statusColor(redis, tk)),
            _ServiceRow(Icons.auto_awesome, t('admin.systemHealth.metrics.openai'), openai, _statusColor(openai, tk)),
          ]),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: StatCell(label: t('admin.systemHealth.metrics.version'), value: version),
            ),
          ),
          const SizedBox(height: 24),
          _eventsCard(context, tk, status, timestamp),
          const SizedBox(height: 16),
          _dependencyCard(context, tk, openai: openai, database: database, redis: redis),
        ],
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
          PillTag(value, color: color),
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

class _ServiceRow {
  const _ServiceRow(this.icon, this.label, this.value, this.color);
  final IconData icon;
  final String label;
  final String value;
  final Color color;
}

// 服務狀態群組：一張卡、多列、hairline 分隔（分隔線縮排對齊文字起點，
// 對齊 dashboard_page 的 _NavGroup 寫法）。
class _ServiceStatusGroup extends StatelessWidget {
  const _ServiceStatusGroup({required this.tk, required this.rows});

  final AppTokens tk;
  final List<_ServiceRow> rows;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(children: [
        for (var i = 0; i < rows.length; i++) ...[
          if (i > 0) Divider(height: 1, thickness: 1, indent: 64, color: tk.edge),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(children: [
              IconTile(rows[i].icon, color: rows[i].color),
              const SizedBox(width: 12),
              Expanded(
                child: Text(rows[i].label,
                    style: Theme.of(context)
                        .textTheme
                        .bodyLarge
                        ?.copyWith(color: tk.inkBody, fontWeight: FontWeight.w500)),
              ),
              PillTag(rows[i].value, color: rows[i].color),
            ]),
          ),
        ],
      ]),
    );
  }
}
