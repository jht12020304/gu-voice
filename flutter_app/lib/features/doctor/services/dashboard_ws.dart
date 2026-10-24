import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/env.dart';
import '../../../data/api/dio_client.dart';
import '../../../data/api/token_store.dart';
import '../../auth/auth_notifier.dart';
import '../../voice/services/ws_manager.dart';

// Shared doctor dashboard WebSocket (/api/v1/ws/dashboard). One connection fans events to
// the alerts + session-list controllers. Reuses the generic WebSocketManager (auth
// handshake, ping, backoff, 4001 refresh) and adds 4003 forbidden_role as a permanent
// stop. No per-event case conversion is needed: consumers read camelCase-event fields and
// simply refetch over HTTP on the snake_case initial_state snapshot.
class DashboardWs {
  DashboardWs() : _ws = WebSocketManager(permanentCloseCodes: const {4003}) {
    _ws.authFailureHandler = () => ApiClient.instance.forceRefresh();
  }

  final WebSocketManager _ws;
  bool _connected = false;
  bool _disposed = false;

  bool get isDisposed => _disposed;

  void ensureConnected() {
    if (_connected || _disposed) return;
    _connected = true;
    _ws.connect('${Env.wsBase}/dashboard', () => TokenStore.instance.accessToken);
  }

  void on(String type, WsHandler handler) => _ws.on(type, handler);
  void off(String type, WsHandler handler) => _ws.off(type, handler);

  void dispose() {
    _disposed = true;
    _ws.disconnect();
  }
}

// The socket also defines the lifetime of doctor data. Profile edits keep it;
// account/role changes close it and rebuild every controller watching it.
final dashboardWsProvider = Provider<DashboardWs?>((ref) {
  final (id, role) = ref.watch(authProvider.select((s) => (s.user?.id, s.user?.role)));
  if (id == null || (role != 'doctor' && role != 'admin')) return null;
  final ws = DashboardWs();
  ref.onDispose(ws.dispose);
  return ws;
});
