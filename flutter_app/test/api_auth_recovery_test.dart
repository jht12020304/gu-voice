import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gu_voice/data/api/dio_client.dart';
import 'package:gu_voice/data/api/token_store.dart';
import 'package:gu_voice/features/auth/auth_notifier.dart';

import 'support/api_stub.dart';

ResponseBody response(int status, [Object body = const {}]) =>
    ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final tokens = TokenStore.instance;
  final client = ApiClient.instance;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://localhost'));
  int cleared = 0;
  int refreshed = 0;

  setUp(() async {
    FlutterSecureStorage.setMockInitialValues({});
    await tokens.clear();
    await tokens.save(access: 'A-access', refresh: 'A-refresh');
    cleared = 0;
    refreshed = 0;
    installApiStub((request) => response(401), refreshDio: refreshDio);
    client.onAuthCleared = () => cleared++;
    refreshDio.httpClientAdapter = StubAdapter((request) {
      refreshed++;
      return {'access_token': 'A-new-access', 'refresh_token': 'A-new-refresh'};
    });
  });
  tearDown(() {
    client.onAuthCleared = null;
  });

  for (final phase in ['refresh', 'retry']) {
    for (final status in [0, 500, 503]) {
      test(
        '$phase ${status == 0 ? 'timeout' : status} 保留登入，回傳真正錯誤且可重試',
        () async {
          Object fail(RequestOptions request) {
            if (status == 0) {
              throw DioException(
                requestOptions: request,
                type: DioExceptionType.receiveTimeout,
              );
            }
            return response(status);
          }

          if (phase == 'refresh') {
            refreshDio.httpClientAdapter = StubAdapter(fail);
          } else {
            installApiStub(
              (request) => request.extra['_retry'] == true
                  ? fail(request)
                  : response(401),
            );
          }
          await expectLater(
            client.dio.get('/protected'),
            throwsA(
              isA<DioException>()
                  .having(
                    (e) => e.response?.statusCode,
                    'status',
                    status == 0 ? null : status,
                  )
                  .having(
                    (e) => e.type,
                    'type',
                    status == 0
                        ? DioExceptionType.receiveTimeout
                        : DioExceptionType.badResponse,
                  ),
            ),
          );
          expect(
            tokens.accessToken,
            phase == 'refresh' ? 'A-access' : 'A-new-access',
          );
          expect(
            await tokens.readRefresh(),
            phase == 'refresh' ? 'A-refresh' : 'A-new-refresh',
          );
          expect(cleared, 0);
          refreshDio.httpClientAdapter = StubAdapter(
            (_) => {
              'access_token': 'recovered',
              'refresh_token': 'recovered-refresh',
            },
          );
          expect(await client.forceRefresh(), isTrue);
        },
      );
    }
  }

  for (final status in [401, 403]) {
    test('refresh $status 確實拒絕憑證時清除登入', () async {
      refreshDio.httpClientAdapter = StubAdapter((_) => response(status));
      await expectLater(
        client.dio.get('/protected'),
        throwsA(isA<DioException>()),
      );
      expect(tokens.accessToken, isNull);
      expect(await tokens.readRefresh(), isNull);
      expect(cleared, 1);
    });
  }

  test('重送仍為 401 登出；資源 403 保留登入', () async {
    for (final status in [403, 401]) {
      installApiStub(
        (request) => response(request.extra['_retry'] == true ? status : 401),
      );
      await expectLater(
        client.dio.get('/protected'),
        throwsA(
          isA<DioException>().having(
            (e) => e.response?.statusCode,
            'status',
            status,
          ),
        ),
      );
      expect(cleared, status == 401 ? 1 : 0);
      expect(tokens.accessToken, status == 401 ? isNull : isNotNull);
    }
  });

  test('並行 401 與 bootstrap 重試共用一次刷新，各自只重送一次', () async {
    final gate = Completer<void>();
    refreshDio.httpClientAdapter = StubAdapter((_) async {
      refreshed++;
      await gate.future;
      return {'access_token': 'fresh', 'refresh_token': 'fresh-refresh'};
    });
    var retried = 0;
    installApiStub((request) {
      if (request.extra['_retry'] != true) return response(401);
      expect(request.headers['Authorization'], 'Bearer fresh');
      retried++;
      return {'ok': true};
    });
    final first = client.dio.get('/one');
    await pumpEventQueue();
    await tokens.load();
    final pending = Future.wait([first, client.dio.get('/two')]);
    await pumpEventQueue();
    expect(refreshed, 1);
    gate.complete();
    await pending;
    expect(retried, 2);
    expect(cleared, 0);
  });

  for (final status in [200, 401, 503]) {
    test('A 的 refresh $status 晚到不覆蓋或登出 B', () async {
      final gate = Completer<void>();
      refreshDio.httpClientAdapter = StubAdapter((_) async {
        await gate.future;
        return response(status, {
          'access_token': 'late-A',
          'refresh_token': 'late-A-refresh',
        });
      });
      final pending = client.dio.get('/protected');
      final check = expectLater(
        pending,
        throwsA(
          isA<DioException>().having(
            (e) => e.type,
            'type',
            DioExceptionType.cancel,
          ),
        ),
      );
      await pumpEventQueue();
      await tokens.clear();
      await tokens.save(access: 'B-access', refresh: 'B-refresh');
      gate.complete();
      await check;
      expect(tokens.accessToken, 'B-access');
      expect(await tokens.readRefresh(), 'B-refresh');
      expect(cleared, 0);
    });
  }

  test('bootstrap 遇 refresh 503 顯示可重試狀態，保留 Keychain 憑證', () async {
    refreshDio.httpClientAdapter = StubAdapter((_) => response(503));
    final container = ProviderContainer();
    addTearDown(container.dispose);
    client.onAuthCleared = container.read(authProvider.notifier).forceLoggedOut;
    await container.read(authProvider.notifier).bootstrap();
    expect(container.read(authProvider).bootOffline, isTrue);
    expect(tokens.accessToken, 'A-access');
    expect(await tokens.readRefresh(), 'A-refresh');
  });

  test('Keychain 依序完成刷新、登出、新登入，重開後仍是 B', () async {
    await Future.wait([
      tokens.save(
        access: 'late-A',
        refresh: 'late-A-refresh',
        newSession: false,
      ),
      tokens.clear(),
      tokens.save(access: 'B-access', refresh: 'B-refresh'),
    ]);
    await tokens.load();
    expect(tokens.accessToken, 'B-access');
    expect(await tokens.readRefresh(), 'B-refresh');
  });
}
