import 'dart:async';
import 'dart:convert';

import 'package:uuid/uuid.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

// Port of frontend/src/services/websocket.ts. Auto-reconnect (exponential backoff),
// 30s heartbeat, app-level auth handshake, ?resumeFrom=<checksum> on reconnect, and
// 4001 auth-failure recovery. Uniform on web + iOS + Android via web_socket_channel.

typedef WsHandler = void Function(dynamic payload, Map message);
typedef TokenProvider = String? Function();
typedef ResumeTokenProvider = Future<String?> Function();
typedef AuthFailureHandler = Future<bool> Function();

enum WsConnState { connecting, open, reconnecting, closed }

const _wsAuthFailureCloseCode = 4001;
const _uuid = Uuid();

class WebSocketManager {
  final int initialRetryDelayMs;
  final int maxRetryDelayMs;
  final int pingIntervalMs;
  final int maxRetries; // 0 = infinite
  // Close codes that are permanent auth-domain failures (e.g. dashboard 4003
  // forbidden_role): stop reconnecting and emit _auth_exhausted.
  final Set<int> permanentCloseCodes;

  WebSocketManager({
    this.initialRetryDelayMs = 1000,
    this.maxRetryDelayMs = 30000,
    this.pingIntervalMs = 30000,
    this.maxRetries = 0,
    this.permanentCloseCodes = const {},
  });

  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  String _url = '';
  TokenProvider _tokenSource = () => null;
  final _listeners = <String, Set<WsHandler>>{};
  int _retryCount = 0;
  Timer? _retryTimer;
  Timer? _pingTimer;
  bool _isManualClose = false;
  bool _isOpen = false;
  WsConnState _connectionState = WsConnState.closed;
  ResumeTokenProvider? resumeTokenProvider;
  AuthFailureHandler? authFailureHandler;

  // Whether this connection cycle already tried "auth-fail -> refresh". MUST NOT reset
  // on open: the backend accepts the socket first, then validates the auth message and
  // may 4001-close after open. Reset only on the FIRST received message (= auth passed).
  bool _hasAttemptedAuthRecovery = false;

  bool get isConnected => _isOpen;
  WsConnState get connectionState => _connectionState;

  void connect(String url, TokenProvider token) {
    _url = url;
    _tokenSource = token;
    _isManualClose = false;
    _retryCount = 0;
    _setState(WsConnState.connecting);
    _createConnection();
  }

  void disconnect() {
    _isManualClose = true;
    _clearTimers();
    resumeTokenProvider = null;
    authFailureHandler = null;
    _hasAttemptedAuthRecovery = false;
    _closeChannel(1000, 'Client disconnect');
    _setState(WsConnState.closed);
  }

  void retry() {
    if (_isOpen || _url.isEmpty) return;
    _clearTimers();
    _isManualClose = false;
    _retryCount = 0;
    _setState(WsConnState.connecting);
    unawaited(_reconnectWithResume());
  }

  void send(String type, [Object payload = const {}]) {
    if (!_isOpen || _channel == null) return;
    _channel!.sink.add(jsonEncode({
      'type': type,
      'id': _uuid.v4(),
      'timestamp': DateTime.now().toUtc().toIso8601String(),
      'payload': payload,
    }));
  }

  void on(String type, WsHandler handler) =>
      _listeners.putIfAbsent(type, () => {}).add(handler);

  void off(String type, WsHandler handler) => _listeners[type]?.remove(handler);

  // ---- internals ----

  void _setState(WsConnState s) {
    if (_connectionState == s) return;
    _connectionState = s;
    _emit('_statechange', {'state': s.name});
  }

  String _resolveToken() => _tokenSource() ?? '';

  Uri _buildUri(String? resumeToken) {
    if (resumeToken == null || resumeToken.isEmpty) return Uri.parse(_url);
    final sep = _url.contains('?') ? '&' : '?';
    return Uri.parse('$_url${sep}resumeFrom=${Uri.encodeComponent(resumeToken)}');
  }

  void _createConnection([String? resumeToken]) {
    final channel = WebSocketChannel.connect(_buildUri(resumeToken));
    _channel = channel;
    _isOpen = false;

    // ready completes when the transport handshake is done (the onopen equivalent).
    channel.ready.then((_) {
      _isOpen = true;
      // Raw top-level {type:'auth', token} — NOT the envelope send() wraps.
      channel.sink.add(jsonEncode({'type': 'auth', 'token': _resolveToken()}));
      _retryCount = 0;
      // Do NOT reset _hasAttemptedAuthRecovery here (see field comment).
      _startPing();
      _setState(WsConnState.open);
      _emit('_connected', {});
    }).catchError((_) {
      // ready failed to connect — onDone below drives reconnect/close.
    });

    _sub = channel.stream.listen(
      (data) {
        // First received message = this cycle's auth passed; re-arm the guard so a
        // future independent 4001 can retry once (not a permanent one-shot).
        _hasAttemptedAuthRecovery = false;
        try {
          final message = jsonDecode(data as String) as Map;
          _emit(message['type'] as String, message['payload'], message);
        } catch (_) {
          // ignore malformed frames
        }
      },
      onError: (_) => _emit('_error', {'message': 'WebSocket error'}),
      onDone: _onDone,
      cancelOnError: false,
    );
  }

  void _onDone() {
    final code = _channel?.closeCode;
    final reason = _channel?.closeReason;
    _isOpen = false;
    _clearTimers();
    _emit('_disconnected', {'code': code, 'reason': reason});

    if (_isManualClose) {
      _setState(WsConnState.closed);
      return;
    }

    // Permanent auth-domain failure (e.g. dashboard 4003 forbidden_role): do not reconnect.
    if (code != null && permanentCloseCodes.contains(code)) {
      _setState(WsConnState.closed);
      _emit('_auth_exhausted', {'code': code});
      return;
    }

    if (code == _wsAuthFailureCloseCode && authFailureHandler != null) {
      if (!_hasAttemptedAuthRecovery) {
        _hasAttemptedAuthRecovery = true;
        _setState(WsConnState.reconnecting);
        unawaited(_recoverFromAuthFailure());
        return;
      }
      _setState(WsConnState.closed);
      _emit('_auth_exhausted', {});
      return;
    }

    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (maxRetries > 0 && _retryCount >= maxRetries) {
      _setState(WsConnState.closed);
      _emit('_max_retries', {});
      return;
    }
    final delay = (initialRetryDelayMs * (1 << _retryCount)).clamp(0, maxRetryDelayMs);
    _retryCount++;
    _setState(WsConnState.reconnecting);
    _emit('_reconnecting', {'attempt': _retryCount, 'delay': delay});
    _retryTimer = Timer(Duration(milliseconds: delay), () => unawaited(_reconnectWithResume()));
  }

  Future<void> _recoverFromAuthFailure() async {
    if (_isManualClose || authFailureHandler == null) return;
    var recovered = false;
    try {
      recovered = await authFailureHandler!();
    } catch (_) {
      recovered = false;
    }
    if (_isManualClose) return;
    if (!recovered) {
      _setState(WsConnState.closed);
      _emit('_auth_exhausted', {});
      return;
    }
    _retryCount = 0;
    _createConnection();
  }

  Future<void> _reconnectWithResume() async {
    if (_isManualClose) return;
    String? resumeToken;
    if (resumeTokenProvider != null) {
      try {
        resumeToken = await resumeTokenProvider!();
      } catch (_) {
        resumeToken = null;
      }
    }
    if (_isManualClose) return;
    _createConnection(resumeToken);
  }

  void _startPing() {
    _pingTimer = Timer.periodic(Duration(milliseconds: pingIntervalMs), (_) => send('ping', {}));
  }

  void _clearTimers() {
    _retryTimer?.cancel();
    _retryTimer = null;
    _pingTimer?.cancel();
    _pingTimer = null;
  }

  void _closeChannel(int code, String reason) {
    _sub?.cancel();
    _sub = null;
    _channel?.sink.close(code, reason);
    _channel = null;
    _isOpen = false;
  }

  void _emit(String type, dynamic payload, [Map? message]) {
    final msg = message ??
        {'type': type, 'id': '', 'timestamp': DateTime.now().toUtc().toIso8601String(), 'payload': payload};
    for (final h in _listeners[type] ?? const <WsHandler>{}) {
      h(payload, msg);
    }
    for (final h in _listeners['*'] ?? const <WsHandler>{}) {
      h(payload, msg);
    }
  }
}
