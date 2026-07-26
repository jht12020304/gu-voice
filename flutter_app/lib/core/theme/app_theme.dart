import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_tokens.dart';

// Light/dark ThemeData from the tailwind/DESIGN.md tokens. Inter as the base sans;
// tabular figures on for data alignment. ponytail: platform CJK fallback handles
// zh/ja/ko glyphs for now — bundle Noto Sans per-locale later if offline kiosks need it.
class AppTheme {
  static const _brand = Color(0xFF2563EB);

  static ThemeData get light => _build(Brightness.light, AppTokens.light);
  static ThemeData get dark => _build(Brightness.dark, AppTokens.dark);

  static ThemeData _build(Brightness brightness, AppTokens tokens) {
    final isDark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: _brand,
      brightness: brightness,
      primary: _brand,
      surface: isDark ? const Color(0xFF0F1117) : Colors.white,
      onSurface: tokens.inkHeading,
      error: tokens.alertCritical,
    );

    final base = isDark ? ThemeData.dark() : ThemeData.light();
    // ponytail: tabular figures applied per-widget on numeric/table text in the
    // charting phase — TextTheme.apply can't set fontFeatures globally.
    final textTheme = GoogleFonts.interTextTheme(base.textTheme).apply(
      bodyColor: tokens.inkBody,
      displayColor: tokens.inkHeading,
    );

    return base.copyWith(
      colorScheme: scheme,
      scaffoldBackgroundColor: isDark ? const Color(0xFF0F1117) : const Color(0xFFF8F9FC),
      textTheme: textTheme,
      extensions: [tokens],
      cardTheme: CardThemeData(
        elevation: 0,
        color: isDark ? const Color(0xFF1E2330) : Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(color: tokens.edge),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: isDark ? const Color(0xFF171B24) : Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: BorderSide(color: tokens.edge),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: BorderSide(color: tokens.edge),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(6),
          borderSide: BorderSide(color: tokens.edgeFocus, width: 2),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: _brand,
          foregroundColor: Colors.white,
          minimumSize: const Size.fromHeight(48),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        ),
      ),
    );
  }
}
