// 標準 integration_test driver 進入點——`flutter drive` 需要這支檔案當作
// `--driver` 目標，才能收集 integration_test 的結果並回報 pass/fail。
// web 平台（經 chromedriver）與 iOS simulator 都走這支。
//
// onScreenshot：測試內呼叫 binding.takeScreenshot(name) 時，把 PNG 寫到
// build/layout_shots/<name>.png（mobile_layout_walkthrough_test 帶
// --dart-define=SHOTS=true 時逐頁截圖，人眼複核用；不帶 SHOTS 時測試端
// 根本不呼叫，這個 callback 閒置）。
//
// 用法見 flutter_app/README.md 的 web 章節與 mobile_layout_walkthrough_test 檔頭。
import 'dart:io';

import 'package:integration_test/integration_test_driver_extended.dart';

Future<void> main() => integrationDriver(
      onScreenshot: (String name, List<int> bytes, [Map<String, Object?>? args]) async {
        final file = File('build/layout_shots/$name.png');
        file.createSync(recursive: true);
        file.writeAsBytesSync(bytes);
        return true;
      },
    );
