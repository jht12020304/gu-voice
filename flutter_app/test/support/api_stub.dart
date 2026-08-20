// 測試用的假 HttpClientAdapter：讓 widget 測試能餵**後端原樣的 snake_case JSON**
// 給真正的 ApiClient，連 Dio 的 camelCase 轉換 interceptor 一起走過一遍。
//
// 為什麼不 mock 掉 ReportsApi/SessionsApi：`patient_facing_localized` 這輪的風險有一半
// 就在「JSONB 巢狀 key 會不會被 interceptor 轉成 camelCase」。從 adapter 這一層注入，
// 測到的才是病患實際會拿到的那條路徑。
//
// 檔名不以 _test.dart 結尾，`flutter test` 不會把它當測試檔收集。

import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:gu_voice/data/api/dio_client.dart';

/// 依請求回傳 JSON（回 null＝該路徑沒設 stub，測試會直接失敗而不是靜默 404）。
typedef StubRouter = Object? Function(RequestOptions options);

bool _inited = false;

/// 已送出的請求（依序），供斷言 body/query 用。
final sentRequests = <RequestOptions>[];

/// 安裝 stub。`ApiClient.instance.dio` 是 `late final`，同一個 process 只能 init 一次，
/// 所以這裡自己記狀態；每次呼叫都會清空 [sentRequests] 並換掉 router。
void installApiStub(StubRouter router) {
  if (!_inited) {
    ApiClient.instance.init();
    _inited = true;
  }
  sentRequests.clear();
  ApiClient.instance.dio.httpClientAdapter = _StubAdapter(router);
}

class _StubAdapter implements HttpClientAdapter {
  _StubAdapter(this.router);
  final StubRouter router;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    sentRequests.add(options);
    final body = router(options);
    if (body == null) {
      return ResponseBody.fromString('{"detail":"no stub"}', 404,
          headers: _jsonHeaders);
    }
    return ResponseBody.fromString(json.encode(body), 200, headers: _jsonHeaders);
  }

  @override
  void close({bool force = false}) {}
}

const _jsonHeaders = {
  Headers.contentTypeHeader: ['application/json'],
};
