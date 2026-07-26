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

  Future<void> _open(AppNotification n) async {
    if (!n.isRead) await ref.read(notificationsProvider.notifier).markRead(n.id);
    final route = n.route();
    if (route != null && mounted) context.go(prefixLngToPath(route, currentLng));
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
    if (st.isLoading && st.notifications.isEmpty) return const Center(child: CircularProgressIndicator());
    if (st.notifications.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(t('dashboard.notifications.emptyTitle'), style: Theme.of(context).textTheme.titleMedium),
          Text(t('dashboard.notifications.emptyMessage')),
        ]),
      );
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(16),
      children: [
        if (st.error != null) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(st.error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        for (final n in st.notifications) _card(context, n),
        if (st.isLoading) const Center(child: Padding(padding: EdgeInsets.all(12), child: CircularProgressIndicator())),
        if (!st.hasMore) Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(t('common.pagination.allLoaded')))),
      ],
    );
  }

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
