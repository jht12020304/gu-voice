import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../state/alerts_controller.dart';
import '../state/notifications_controller.dart';

// 5-tab doctor shell (bottom nav). Each tab route renders DoctorShell(index, body). The
// Alerts/Notifications tabs carry live badges from their controllers (which also keep the
// dashboard WS connected across tabs).
class DoctorShell extends ConsumerWidget {
  const DoctorShell({super.key, required this.index, required this.child});
  final int index;
  final Widget child;

  static const _routes = ['/dashboard', '/sessions', '/alerts', '/notifications', '/settings'];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unacked = ref.watch(alertsProvider.select((s) => s.unacknowledgedCount));
    final unread = ref.watch(notificationsProvider.select((s) => s.unreadCount));

    String cap(int n) => n > 99 ? '99+' : '$n';

    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => context.go(prefixLngToPath(_routes[i], currentLng)),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.dashboard_outlined),
            selectedIcon: const Icon(Icons.dashboard),
            label: t('dashboard.sidebar.nav.dashboard'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.forum_outlined),
            selectedIcon: const Icon(Icons.forum),
            label: t('dashboard.sidebar.nav.sessions'),
          ),
          NavigationDestination(
            icon: Badge(label: Text(cap(unacked)), isLabelVisible: unacked > 0, child: const Icon(Icons.warning_amber_outlined)),
            label: t('dashboard.sidebar.nav.redFlagAlerts'),
          ),
          NavigationDestination(
            icon: Badge(label: Text(cap(unread)), isLabelVisible: unread > 0, child: const Icon(Icons.notifications_outlined)),
            label: t('common.header.notifications'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.settings_outlined),
            selectedIcon: const Icon(Icons.settings),
            label: t('dashboard.sidebar.nav.settings'),
          ),
        ],
      ),
    );
  }
}
