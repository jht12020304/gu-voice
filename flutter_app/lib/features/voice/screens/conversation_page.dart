import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/i18n/loc.dart';
import '../../../core/router/lng.dart';
import '../../../core/theme/app_tokens.dart';
import '../../../data/api/sessions_api.dart';
import '../../../data/models/session.dart';
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
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(f.title, style: TextStyle(color: sev(f.severity), fontWeight: FontWeight.w600)),
                  if (f.description != null && f.description!.isNotEmpty)
                    Text(f.description!, style: TextStyle(color: sev(f.severity), fontSize: 13)),
                ]),
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
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: s.messages.length,
      itemBuilder: (context, i) {
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
    if (s.isAIResponding) {
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
          ],
        ),
      ),
    );
  }

  Widget _iconBtn({required IconData icon, required String label, required VoidCallback onTap}) {
    return TextButton.icon(onPressed: onTap, icon: Icon(icon), label: Text(label));
  }
}
