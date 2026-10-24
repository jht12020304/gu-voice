import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../voice/services/ws_manager.dart' show WsHandler;
import '../services/dashboard_ws.dart';

/// 請求序號：發請求前 [next]，回應落地時用 [isStale] 擋掉被後發請求作廢的舊回應
/// （切篩選／換月／WS 觸發重抓時，先發的那趟可能後到）。三個 controller 與四個
/// 分頁頁面原本各自手寫一份 `++_request` / `request != _request`，收斂到這裡。
class RequestSeq {
  int _seq = 0;

  /// 目前序號——給「不另起序號、但要被之後的 [next] 作廢」的追加分頁用。
  int get current => _seq;

  int next() => ++_seq;

  bool isStale(int request) => request != _seq;
}

/// 把 [handler] 掛上 dashboard WS 的 [events]，provider 釋放時一併解掉。
void bindWsEvents(Ref ref, DashboardWs ws, List<String> events, WsHandler handler) {
  for (final e in events) {
    ws.on(e, handler);
  }
  ref.onDispose(() {
    for (final e in events) {
      ws.off(e, handler);
    }
  });
}
