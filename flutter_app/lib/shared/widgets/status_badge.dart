import 'package:flutter/material.dart';

import '../../core/i18n/loc.dart';
import '../../core/theme/app_tokens.dart';

// Session status -> semantic color + i18n label (patient.home.status* keys).
class StatusBadge extends StatelessWidget {
  const StatusBadge(this.status, {super.key});
  final String status;

  static const _labelKey = {
    'completed': 'patient.home.statusCompleted',
    'in_progress': 'patient.home.statusInProgress',
    'waiting': 'patient.home.statusWaiting',
    'aborted_red_flag': 'patient.home.statusAbortedRedFlag',
    'cancelled': 'patient.home.statusCancelled',
  };

  Color _color(AppTokens tk) {
    switch (status) {
      case 'completed':
        return tk.statusCompleted;
      case 'in_progress':
        return tk.statusInProgress;
      case 'waiting':
        return tk.statusWaiting;
      case 'aborted_red_flag':
        return tk.statusRedFlag;
      case 'cancelled':
        return tk.statusCancelled;
      default:
        return tk.statusCompleted; // unknown -> completed style (matches web fallback)
    }
  }

  @override
  Widget build(BuildContext context) {
    final tk = Theme.of(context).extension<AppTokens>()!;
    final color = _color(tk);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(9999),
      ),
      child: Text(
        t(_labelKey[status] ?? 'patient.home.statusCompleted'),
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}
