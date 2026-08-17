// 標準 integration_test web driver 進入點——`flutter drive` 在 web 平台上
// 需要這支檔案當作 `--driver` 目標，才能透過 chromedriver 收集
// integration_test 的結果並回報 pass/fail（純樣板，來自
// package:integration_test 官方文件，不含任何專案邏輯）。
//
// 用法見 flutter_app/README.md 的 web 章節。
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver();
