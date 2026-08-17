import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    // 開麥前的「這台機器錄不錄得到音」探針。沒有它，無音訊輸入的機器一進問診頁
    // 就 SIGABRT（見 MicProbe.swift）。
    MicProbe.register(with: engineBridge.applicationRegistrar.messenger())
  }
}
