import 'package:flutter/material.dart';

// Non-Material semantic tokens from tailwind.config.js / DESIGN.md that ColorScheme
// can't hold: 4-level alerts, session-status, chat roles, ink hierarchy, edges.
// Access via Theme.of(context).extension<AppTokens>()!.
@immutable
class AppTokens extends ThemeExtension<AppTokens> {
  // Alerts (color+bg+border+text; colorblind-safe when paired with icon+text).
  final Color alertCritical, alertCriticalBg;
  final Color alertHigh, alertHighBg;
  final Color alertMedium, alertMediumBg;
  final Color alertSuccess, alertSuccessBg;

  // Session status.
  final Color statusWaiting, statusInProgress, statusCompleted, statusRedFlag, statusCancelled;

  // Chat bubbles.
  final Color chatBg, chatPatient, chatPatientBg, chatAi, chatAiBg, chatSystem, chatBorder;

  // Ink hierarchy (never pure black) + edges.
  final Color inkHeading, inkBody, inkSecondary, inkMuted, inkPlaceholder;
  final Color edge, edgeHover, edgeFocus;

  const AppTokens({
    required this.alertCritical,
    required this.alertCriticalBg,
    required this.alertHigh,
    required this.alertHighBg,
    required this.alertMedium,
    required this.alertMediumBg,
    required this.alertSuccess,
    required this.alertSuccessBg,
    required this.statusWaiting,
    required this.statusInProgress,
    required this.statusCompleted,
    required this.statusRedFlag,
    required this.statusCancelled,
    required this.chatBg,
    required this.chatPatient,
    required this.chatPatientBg,
    required this.chatAi,
    required this.chatAiBg,
    required this.chatSystem,
    required this.chatBorder,
    required this.inkHeading,
    required this.inkBody,
    required this.inkSecondary,
    required this.inkMuted,
    required this.inkPlaceholder,
    required this.edge,
    required this.edgeHover,
    required this.edgeFocus,
  });

  static const light = AppTokens(
    alertCritical: Color(0xFFDC2626), alertCriticalBg: Color(0xFFFEF2F2),
    alertHigh: Color(0xFFEA580C), alertHighBg: Color(0xFFFFF7ED),
    alertMedium: Color(0xFFD97706), alertMediumBg: Color(0xFFFFFBEB),
    alertSuccess: Color(0xFF16A34A), alertSuccessBg: Color(0xFFF0FDF4),
    statusWaiting: Color(0xFF64748B), statusInProgress: Color(0xFF2563EB),
    statusCompleted: Color(0xFF16A34A), statusRedFlag: Color(0xFFDC2626),
    statusCancelled: Color(0xFF6B7280),
    chatBg: Color(0xFFFAF9F6), chatPatient: Color(0xFF2563EB), chatPatientBg: Color(0xFFDBEAFE),
    chatAi: Color(0xFFEA580C), chatAiBg: Color(0xFFFFF7ED), chatSystem: Color(0xFF64748B),
    chatBorder: Color(0xFFDEDBD6),
    inkHeading: Color(0xFF061B31), inkBody: Color(0xFF425466), inkSecondary: Color(0xFF64748D),
    inkMuted: Color(0xFF8898AA), inkPlaceholder: Color(0xFFA3B1C6),
    edge: Color(0xFFE5EDF5), edgeHover: Color(0xFFD0DAE8), edgeFocus: Color(0xFF2563EB),
  );

  // Dark: Linear-style blue-black stacking for night shift (DESIGN.md palette).
  static const dark = AppTokens(
    alertCritical: Color(0xFFF87171), alertCriticalBg: Color(0xFF2A1416),
    alertHigh: Color(0xFFFB923C), alertHighBg: Color(0xFF2A1C10),
    alertMedium: Color(0xFFFBBF24), alertMediumBg: Color(0xFF2A2410),
    alertSuccess: Color(0xFF4ADE80), alertSuccessBg: Color(0xFF10241A),
    statusWaiting: Color(0xFF8A8F98), statusInProgress: Color(0xFF60A5FA),
    statusCompleted: Color(0xFF4ADE80), statusRedFlag: Color(0xFFF87171),
    statusCancelled: Color(0xFF6B7280),
    chatBg: Color(0xFF171B24), chatPatient: Color(0xFF60A5FA), chatPatientBg: Color(0xFF1B2537),
    chatAi: Color(0xFFFB923C), chatAiBg: Color(0xFF2A1C10), chatSystem: Color(0xFF8A8F98),
    chatBorder: Color(0x14FFFFFF),
    inkHeading: Color(0xFFF7F8F8), inkBody: Color(0xFFD0D6E0), inkSecondary: Color(0xFFB0B6C0),
    inkMuted: Color(0xFF8A8F98), inkPlaceholder: Color(0xFF6B7280),
    edge: Color(0x14FFFFFF), edgeHover: Color(0x24FFFFFF), edgeFocus: Color(0xFF60A5FA),
  );

  @override
  AppTokens copyWith() => this; // ponytail: tokens are const sets, no partial override needed

  @override
  AppTokens lerp(ThemeExtension<AppTokens>? other, double t) =>
      t < 0.5 ? this : (other as AppTokens? ?? this);
}
