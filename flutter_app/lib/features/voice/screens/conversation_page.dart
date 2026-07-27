import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
import '../models/chat_message.dart';
import '../services/ws_manager.dart';
import '../state/conversation_controller.dart';
import '../state/settings_notifier.dart';

class ConversationPage extends ConsumerStatefulWidget {
  const ConversationPage({super.key, required this.sessionId, this.session});
  final String sessionId;
  final Session? session;

  @override
  ConsumerState<ConversationPage> createState() => _ConversationPageState();
}

class _ConversationPageState extends ConsumerState<ConversationPage> {
  final _textCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    Future.microtask(_init);
  }

  @override
  void dispose() {
    _textCtrl.dispose();
    super.dispose();
  }

  Future<void> _init() async {
    final session = widget.session ?? await SessionsApi().getSession(widget.sessionId);
    if (!mounted) return;
    await ref.read(conversationControllerProvider.notifier).start(session);
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(conversationControllerProvider);

    // On completion, route to the thank-you page (red-flag variant carried via extra).
    //
    // Both fields are selected together on purpose. `_onSessionStatus` sets
    // `completed` and `abortedRedFlag` in ONE copyWith, so listening on `completed`
    // alone and then reading `s.abortedRedFlag` would read the PREVIOUS build's
    // snapshot — still false — and a red-flag-aborted patient would get the generic
    // thank-you page plus its 8s auto-redirect home, never seeing "tell the staff
    // here" (voice-pipeline-invariants #11). Reading both off the same emission
    // makes that stale read structurally impossible.
    ref.listen(
      conversationControllerProvider.select((v) => (v.completed, v.abortedRedFlag)),
      (_, next) {
        final (completed, abortedRedFlag) = next;
        if (completed) {
          context.go(
            prefixLngToPath('/patient/session/${widget.sessionId}/thank-you', currentLng),
            extra: {'abortedRedFlag': abortedRedFlag},
          );
        }
      },
    );

    return Scaffold(
      appBar: AppBar(
        title: Text(t('conversation.title')),
        actions: [
          TextButton(
            onPressed: () => ref.read(conversationControllerProvider.notifier).endSession(),
            child: Text(t('conversation.endSession')),
          ),
        ],
      ),
      body: Column(
        children: [
          if (s.connection != WsConnState.open) _banner(context, s.connection),
          if (s.redFlags.isNotEmpty) _redFlagBanner(context, s),
          if (s.supervisorDegraded || s.guidance != null) _supervisorBanner(context, s),
          if (s.error != null) _errorBanner(context, s.error!),
          Expanded(child: _transcript(context, s)),
          _statusBar(context, s),
          _textInput(context, s),
          _controls(context, s),
        ],
      ),
    );
  }

  // Stacked, severity-colored, acknowledge-able red-flag banner (≤3 sorted, then overflow
  // count) — safety-UI parity with the React ConversationPage.
  Widget _supervisorBanner(BuildContext context, ConversationState s) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final g = s.guidance;
    return Container(
      width: double.infinity,
      color: tk.alertMediumBg,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (s.supervisorDegraded)
          Text(t('conversation.supervisor.degraded'), style: TextStyle(color: tk.alertMedium)),
        if (g != null && g.nextFocus.isNotEmpty)
          Text('${t('conversation.supervisor.hintLabel')}: ${g.nextFocus}',
              style: TextStyle(color: tk.alertMedium, fontWeight: FontWeight.w600)),
        if (g != null && g.missingHpi.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Wrap(spacing: 6, runSpacing: 4, children: [
              Text('${t('conversation.supervisor.missingLabel')}:', style: TextStyle(color: tk.alertMedium)),
              for (final h in g.missingHpi)
                Chip(
                  label: Text(t('conversation.supervisor.hpi.$h')),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
            ]),
          ),
      ]),
    );
  }

  Widget _banner(BuildContext context, WsConnState conn) {
    final label = conn == WsConnState.reconnecting
        ? t('conversation.connection.reconnecting')
        : t('conversation.error.disconnected');
    return Container(
      width: double.infinity,
      color: Theme.of(context).colorScheme.secondaryContainer,
      padding: const EdgeInsets.all(8),
      child: Text(label, textAlign: TextAlign.center),
    );
  }

  /// 顯示中的紅旗共用的後端病患指引；不一致或任一則缺少時回 null（→ 用本地
  /// 保守版 fallback）。不一致時不能挑其中一則：那會對另一則的狀態說謊。
  static String? _sharedPatientNotice(List<RedFlagEvent> shown) {
    if (shown.isEmpty) return null;
    final first = shown.first.patientNotice;
    if (first == null || first.isEmpty) return null;
    for (final f in shown) {
      if (f.patientNotice != first) return null;
    }
    return first;
  }

  Widget _redFlagBanner(BuildContext context, ConversationState s) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    const rank = {'critical': 0, 'high': 1, 'medium': 2};
    // Unacknowledged first, then by severity, newest last; show up to 3 + overflow count.
    final sorted = [...s.redFlags]..sort((a, b) {
        if (a.isAcknowledged != b.isAcknowledged) return a.isAcknowledged ? 1 : -1;
        return (rank[a.severity] ?? 3).compareTo(rank[b.severity] ?? 3);
      });
    final shown = sorted.take(3).toList();
    final overflow = sorted.length - shown.length;
    Color sev(String s) => switch (s) { 'critical' => tk.alertCritical, 'high' => tk.alertHigh, _ => tk.alertMedium };

    return Container(
      width: double.infinity,
      color: tk.alertCriticalBg,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final f in shown)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.warning_amber_rounded, color: sev(f.severity), size: 20),
              const SizedBox(width: 8),
              Expanded(
                // 病患橫幅只呈現「症狀名（title，後端依場次語言解析）」＋下方固定的
                // kiosk 指引。醫師向欄位（description / suggestedActions）一律不渲染：
                // 實測 description 是臨床推理文字（含鑑別診斷、「建議立即急診評估」），
                // suggestedActions 是醫囑處置（「立即安排急診評估」），對已坐在候診區
                // 的病患既看不懂又造成恐慌，且違反 kiosk 措辭鐵律。
                // 與 React ConversationPage.tsx 的紅旗橫幅行為一致。
                //
                // 2026-07-27 Gate：結構性防線已補齊——RedFlagEvent 型別不再有
                // description / suggestedActions，conversation_controller._onRedFlag
                // 也不 ingest，所以 store 裡根本沒有值可印（與 React 同構）。
                // title 為空（後端解析不到 canonical 顯示名）時退回中性的在地化說法，
                // 否則橫幅只剩一個驚嘆號圖示，病患不知道發生什麼事。
                child: Text(
                  f.title.trim().isEmpty ? t('conversation.redFlag.generic') : f.title,
                  style: TextStyle(color: sev(f.severity), fontWeight: FontWeight.w600),
                ),
              ),
              if (!f.isAcknowledged)
                TextButton(
                  onPressed: () => ref.read(conversationControllerProvider.notifier).acknowledgeRedFlag(f.id),
                  child: Text(t('dashboard.alert.acknowledge')),
                )
              else
                Icon(Icons.check_circle, color: tk.statusCompleted, size: 18),
            ]),
          ),
        if (overflow > 0)
          Text(t('conversation.redFlag.more', args: {'count': overflow}), style: TextStyle(color: tk.alertCritical, fontSize: 12)),
        // 病患面唯一的行動指引：院內候診 kiosk，病患已在現場 →「原處稍候、
        // 告知現場醫護」，不得出現「盡速就醫／立即急診」這類含糊指引。
        //
        // 優先用後端下發的 patientNotice：只有後端知道這則紅旗有沒有**真的**建立
        // 醫師通知（未指派場次要 fan-out 給在職醫師，可能 0 位或寫入失敗），
        // 前端自己拼就會對病患說謊。只有在所有顯示中的紅旗 notice 完全一致時才
        // 當共用結尾，否則退回本地保守版 fallback（＝後端 _flagged 的同一句話，
        // 由 test/red_flag_banner_wording_test.dart 逐字釘住）。
        // 退回方向是 under-claim（少宣稱一層），不會說謊。
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(
            _sharedPatientNotice(shown) ?? t('conversation.redFlag.patientNotice'),
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 12),
          ),
        ),
      ]),
    );
  }

  Widget _textInput(BuildContext context, ConversationState s) {
    final online = s.connection == WsConnState.open;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Row(children: [
        Expanded(
          child: TextField(
            controller: _textCtrl,
            enabled: online,
            textInputAction: TextInputAction.send,
            onSubmitted: online ? (_) => _sendText() : null,
            decoration: InputDecoration(
              isDense: true,
              hintText: t(online ? 'conversation.input.textPlaceholder' : 'conversation.input.sendOffline'),
            ),
          ),
        ),
        IconButton(
          icon: const Icon(Icons.send),
          tooltip: t('conversation.input.send'),
          onPressed: online ? _sendText : null,
        ),
      ]),
    );
  }

  void _sendText() {
    final text = _textCtrl.text;
    if (text.trim().isEmpty) return;
    ref.read(conversationControllerProvider.notifier).sendText(text);
    _textCtrl.clear();
  }

  Widget _errorBanner(BuildContext context, String error) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    return Container(
      width: double.infinity,
      color: tk.alertHighBg,
      padding: const EdgeInsets.all(8),
      child: Text(error, style: TextStyle(color: tk.alertHigh)),
    );
  }

  Widget _transcript(BuildContext context, ConversationState s) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    // `reverse: true` + reversed indexing pins the newest turn at the bottom and keeps
    // it visible as the list grows. Without it the transcript never scrolls: from about
    // the 4th turn on, the AI's current question sits below the fold and the patient is
    // looking at a stale screen (TODO G10). Cheaper and jitter-free compared with a
    // ScrollController animating to the extent on every append.
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      reverse: true,
      itemCount: s.messages.length,
      itemBuilder: (context, ri) {
        final i = s.messages.length - 1 - ri;
        final m = s.messages[i];
        final isPatient = m.sender == 'patient';
        final isSystem = m.sender == 'system';
        final align = isSystem
            ? Alignment.center
            : isPatient
                ? Alignment.centerRight
                : Alignment.centerLeft;
        final bg = isSystem ? tk.chatBg : (isPatient ? tk.chatPatientBg : tk.chatAiBg);
        return Align(
          alignment: align,
          child: Container(
            margin: const EdgeInsets.symmetric(vertical: 4),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
            decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16)),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(child: Text(m.content.isEmpty && m.isStreaming ? '…' : m.content)),
                if (m.sender == 'assistant' && m.ttsAudioChunks.isNotEmpty) ...[
                  const SizedBox(width: 6),
                  InkWell(
                    onTap: () => ref.read(conversationControllerProvider.notifier).replay(m.id),
                    child: const Icon(Icons.replay, size: 18),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _statusBar(BuildContext context, ConversationState s) {
    String key;
    // userPaused first: while paused the bar used to keep saying "請直接開始說話",
    // telling the patient to do the one thing that cannot work (TODO G-medium).
    if (s.userPaused) {
      key = 'conversation.voiceControl.pausedBanner';
    } else if (s.isAIResponding) {
      key = 'conversation.status.speaking';
    } else if (s.sttProcessing) {
      key = 'conversation.status.transcribing';
    } else if (s.noSpeechHint) {
      key = 'conversation.status.noSpeechDetected';
    } else if (s.isRecording) {
      key = 'conversation.status.listening';
    } else {
      key = 'conversation.status.idle';
    }
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        children: [
          if (s.isRecording) _waveform(context, s.waveform),
          Text(t(key, args: {'duration': s.recordingDuration.toStringAsFixed(0)}),
              style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }

  Widget _waveform(BuildContext context, List<double> bars) {
    final color = Theme.of(context).colorScheme.primary;
    return SizedBox(
      height: 36,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          for (final b in bars)
            Container(
              width: 3,
              height: (4 + b * 32).clamp(4, 36),
              margin: const EdgeInsets.symmetric(horizontal: 1),
              decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2)),
            ),
        ],
      ),
    );
  }

  Widget _controls(BuildContext context, ConversationState s) {
    final settings = ref.watch(settingsProvider);
    final ctrl = ref.read(conversationControllerProvider.notifier);
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
          children: [
            _iconBtn(
              icon: s.userPaused ? Icons.play_arrow : Icons.pause,
              label: t(s.userPaused ? 'conversation.voiceControl.resume' : 'conversation.voiceControl.pause'),
              onTap: () => s.userPaused ? ctrl.resume() : ctrl.pause(),
            ),
            _iconBtn(
              icon: settings.ttsMuted ? Icons.volume_off : Icons.volume_up,
              label: t(settings.ttsMuted ? 'conversation.tts.unmuteLabel' : 'conversation.tts.muteLabel'),
              onTap: () {
                ref.read(settingsProvider.notifier).toggleTtsMuted();
                ctrl.onTtsMuteToggled(ref.read(settingsProvider).ttsMuted);
              },
            ),
            _iconBtn(
              icon: Icons.speed,
              label: t('conversation.tts.speedLabel', args: {'rate': settings.ttsSpeed}),
              onTap: () => ref.read(settingsProvider.notifier).cycleSpeed(),
            ),
            // "我說完了" — skip the 2s silence window. Only useful while actually
            // recording, so it is disabled otherwise rather than silently doing nothing.
            _iconBtn(
              icon: Icons.done_all,
              label: t('conversation.voiceControl.finishSpeaking'),
              onTap: s.isRecording && !s.userPaused ? ctrl.finishSpeaking : null,
            ),
          ],
        ),
      ),
    );
  }

  /// `onTap: null` renders the button disabled (Material greys it out) — used for
  /// "我說完了", which only makes sense mid-utterance.
  Widget _iconBtn({required IconData icon, required String label, VoidCallback? onTap}) {
    return TextButton.icon(onPressed: onTap, icon: Icon(icon), label: Text(label));
  }
}
