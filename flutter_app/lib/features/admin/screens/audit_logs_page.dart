import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/i18n/loc.dart';
import '../../../data/api/admin_api.dart';
import '../../../shared/format.dart';

// Port of frontend/src/screens/admin/AuditLogsPage.tsx.
// Cursor-paginated audit log list with an optional server-side `action` filter and
// infinite scroll. Rows are untyped Maps from getAuditLogs; every field is read
// defensively (backend key casing varies) rather than through a model.
class AuditLogsPage extends StatefulWidget {
  const AuditLogsPage({super.key});

  @override
  State<AuditLogsPage> createState() => _AuditLogsPageState();
}

class _AuditLogsPageState extends State<AuditLogsPage> {
  final _api = AdminApi();
  final _scroll = ScrollController();
  Timer? _debounce;

  List<Map> _logs = [];
  String? _cursor;
  bool _hasMore = true;
  bool _loading = true;
  String? _error;
  String _action = '';

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) _fetchMore();
    });
    Future.microtask(() => _fetch(reset: true));
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _fetch({required bool reset}) async {
    setState(() {
      _loading = true;
      if (reset) _error = null;
    });
    try {
      final page = await _api.getAuditLogs(
        cursor: reset ? null : _cursor,
        action: _action.trim().isEmpty ? null : _action.trim(),
      );
      if (!mounted) return;
      setState(() {
        _logs = reset ? page.data : [..._logs, ...page.data];
        _cursor = page.nextCursor;
        _hasMore = page.hasMore;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = t('admin.audit.loadFailed');
      });
    }
  }

  Future<void> _fetchMore() async {
    if (!_hasMore || _loading || _cursor == null) return;
    await _fetch(reset: false);
  }

  void _onFilter(String q) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      setState(() => _action = q);
      _fetch(reset: true);
    });
  }

  // Defensive read: first non-empty value across candidate keys (snake/camel variants).
  String? _read(Map m, List<String> keys) {
    for (final k in keys) {
      final v = m[k];
      if (v != null && v.toString().trim().isNotEmpty) return v.toString();
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(t('admin.audit.title')),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: t('admin.audit.refresh'),
            onPressed: _loading ? null : () => _fetch(reset: true),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: TextField(
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.filter_list),
                labelText: t('admin.audit.filterAction'),
                hintText: t('admin.audit.filterActionPlaceholder'),
              ),
              onChanged: _onFilter,
            ),
          ),
          Expanded(child: _body(context)),
        ],
      ),
    );
  }

  Widget _body(BuildContext context) {
    if (_loading && _logs.isEmpty) return const Center(child: CircularProgressIndicator());
    if (_error != null && _logs.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 8),
          TextButton(onPressed: () => _fetch(reset: true), child: Text(t('common.retry'))),
        ]),
      );
    }
    if (_logs.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('admin.audit.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
          Text(t('admin.audit.emptyMessage')),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: () => _fetch(reset: true),
      child: ListView(
        controller: _scroll,
        padding: const EdgeInsets.all(16),
        children: [
          for (final log in _logs) _card(context, log),
          if (_loading && _logs.isNotEmpty)
            const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
          if (!_hasMore)
            Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
        ],
      ),
    );
  }

  Widget _card(BuildContext context, Map log) {
    final theme = Theme.of(context);
    final action = _read(log, ['action']) ?? '-';
    final actor = _read(log, ['actorId', 'actor_id', 'userId', 'user_id']);
    final target = _read(log, ['targetId', 'target_id', 'resourceId', 'resource_id']);
    final resourceType = _read(log, ['resourceType', 'resource_type', 'targetType', 'target_type']);
    final createdAt = _read(log, ['createdAt', 'created_at']);
    final ip = _read(log, ['ipAddress', 'ip_address', 'ip']);
    final details = log['details'];
    final detailsText = (details == null || details.toString().trim().isEmpty) ? null : details.toString();

    final meta = <String>[
      if (actor != null) '${t('admin.audit.colUser')}: $actor',
      if (resourceType != null) '${t('admin.audit.colResourceType')}: $resourceType',
      if (target != null) '${t('admin.audit.colResourceId')}: $target',
      if (ip != null) '${t('admin.audit.colIp')}: $ip',
    ];

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(action,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: theme.colorScheme.primary,
                  )),
            ),
            Text(formatDateTime(createdAt), style: theme.textTheme.bodySmall),
          ]),
          if (meta.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(meta.join('  ·  '), style: theme.textTheme.bodySmall),
          ],
          if (detailsText != null) ...[
            const SizedBox(height: 6),
            Text(detailsText,
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
          ],
        ]),
      ),
    );
  }
}
