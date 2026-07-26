import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/config/env.dart';
import '../../../data/api/dio_client.dart';
import '../../../data/api/token_store.dart';
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

  void ensureConnected() {
    if (_connected) return;
    _connected = true;
    _ws.connect('${Env.wsBase}/dashboard', () => TokenStore.instance.accessToken);
  }

  void on(String type, WsHandler handler) => _ws.on(type, handler);
  void off(String type, WsHandler handler) => _ws.off(type, handler);

  void dispose() => _ws.disconnect();
}

final dashboardWsProvider = Provider<DashboardWs>((ref) {
  final ws = DashboardWs();
  ref.onDispose(ws.dispose);
  return ws;
});
