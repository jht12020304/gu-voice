import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/models/notification.dart';
import '../../../shared/format.dart';
import '../state/notifications_controller.dart';

class NotificationPage extends ConsumerStatefulWidget {
  const NotificationPage({super.key});

  @override
  ConsumerState<NotificationPage> createState() => _NotificationPageState();
}

class _NotificationPageState extends ConsumerState<NotificationPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 300) {
        ref.read(notificationsProvider.notifier).fetchMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  bool _refreshing = false;

  void _open(AppNotification n) {
    // Not awaited. `markRead` writes the optimistic state — the card's unread styling and
    // the shell's tab badge both read that same state — synchronously, *before* it sends
    // the POST, so everything the doctor can see is already correct. Awaiting it only
    // bought a 200-800 ms window (up to Dio's 30 s timeout on a stalled request) in which
    // the single most-used gesture on the iOS app appeared to do nothing at all.
    if (!n.isRead) unawaited(ref.read(notificationsProvider.notifier).markRead(n.id));
    final route = n.route();
    if (route != null) context.go(prefixLngToPath(route, currentLng));
  }

  Future<void> _refresh() async {
    setState(() => _refreshing = true);
    try {
      await ref.read(notificationsProvider.notifier).fetch();
    } finally {
      if (mounted) setState(() => _refreshing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final st = ref.watch(notificationsProvider);
    return Scaffold(
      appBar: AppBar(
        title: Text(t('dashboard.notifications.title')),
        actions: [
          TextButton(
            onPressed: () => ref.read(notificationsProvider.notifier).markAllRead(),
            child: Text(t('dashboard.notifications.markAllRead')),
          ),
        ],
      ),
      body: _body(context, st),
    );
  }

  Widget _body(BuildContext context, NotifState st) {
    if (st.isLoading && st.notifications.isEmpty && !_refreshing) {
      return const Center(child: CircularProgressIndicator());
    }

    // Error BEFORE empty, and this order is the whole point. route_guard.dart makes this
    // the landing page for a doctor on iOS, and `fetch()` sets `error` but renders
    // nothing when the list is empty — so a failed first load (cold launch on cellular,
    // Railway waking up, a moment of no signal) showed a confident 「沒有新通知」. The one
    // screen a doctor opens to check whether anything needs them was claiming nothing
    // did, with no error, no retry and no way to tell it apart from a genuinely quiet
    // day. Mirrors alert_list_page's error branch.
    if (st.error != null && st.notifications.isEmpty) {
      return _pullable(
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(st.error!),
            const SizedBox(height: 8),
            FilledButton(
              onPressed: () => ref.read(notificationsProvider.notifier).fetch(),
              child: Text(t('common.retry')),
            ),
          ]),
        ),
      );
    }

    if (st.notifications.isEmpty) {
      return _pullable(
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(t('dashboard.notifications.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
            Text(t('dashboard.notifications.emptyMessage')),
          ]),
        ),
      );
    }

    // ListView.builder, not ListView(children: [...]): rows past the first page stay
    // offscreen instead of being built and rebuilt on every state write — and this
    // controller refetches on every dashboard WS event, so that is once per patient
    // action across the whole clinic.
    final tail = (st.isLoading && !_refreshing) || !st.hasMore ? 1 : 0;
    final lead = st.error != null ? 1 : 0;
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.builder(
        controller: _scroll,
        padding: const EdgeInsets.all(16),
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: lead + st.notifications.length + tail,
        itemBuilder: (context, i) {
          if (lead == 1 && i == 0) {
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(st.error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            );
          }
          final index = i - lead;
          if (index < st.notifications.length) return _card(context, st.notifications[index]);
          // The trailing slot is either the paginate spinner or the end-of-list marker.
          // `_refreshing` keeps a pull-to-refresh from also spinning down here, which
          // would read as two simultaneous loads.
          return st.isLoading && !_refreshing
              ? const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator()))
              : Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded'))));
        },
      ),
    );
  }

  /// RefreshIndicator needs a scrollable child, and a bare `Center` is not one — so the
  /// empty and error states get a full-height scroll view that is pullable anyway.
  /// Without this, the two screens that most need a way to retry are the two that cannot.
  Widget _pullable({required Widget child}) => RefreshIndicator(
        onRefresh: _refresh,
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: child,
            ),
          ),
        ),
      );

  Widget _card(BuildContext context, AppNotification n) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final routable = n.route() != null;
    return Opacity(
      opacity: n.isRead ? 0.75 : 1,
      child: Card(
        margin: const EdgeInsets.symmetric(vertical: 4),
        shape: n.isRead
            ? null
            : RoundedRectangleBorder(borderRadius: BorderRadius.circular(8), side: BorderSide(color: tk.edgeFocus)),
        child: ListTile(
          onTap: () => _open(n),
          title: Row(children: [
            Flexible(child: Text(n.title, style: const TextStyle(fontWeight: FontWeight.w600))),
            if (!n.isRead) ...[
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                decoration: BoxDecoration(color: tk.alertCriticalBg, borderRadius: BorderRadius.circular(4)),
                child: Text(t('dashboard.notifications.unreadBadge'), style: TextStyle(color: tk.alertCritical, fontSize: 11)),
              ),
            ],
          ]),
          subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (n.body != null) Text(n.body!),
            Text(formatDateTime(n.createdAt), style: Theme.of(context).textTheme.bodySmall),
          ]),
          trailing: routable ? Text(t('dashboard.alert.viewDetail'), style: Theme.of(context).textTheme.bodySmall) : null,
        ),
      ),
    );
  }
}
