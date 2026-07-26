plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// ── Release 簽章 ──────────────────────────────────────────────────────────────
// 正式簽章資訊放在 android/key.properties（含金鑰密碼；已在 android/.gitignore，
// 絕對不要 commit，也不要塞進 CI image 或 Dockerfile）。
//
// 為什麼不像 Flutter 範本那樣 fallback 到 debug 金鑰：debug 金鑰簽出的 release
// 產物無法上架、無法覆蓋安裝正式版、且任何人都能用公開的 debug key 重簽同一個
// applicationId — 而這一切是「靜默」發生的，build 會成功，問題要到上架或安裝時
// 才爆。所以這裡改成缺設定就讓 release build 明確失敗並印出補設定的步驟。
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = java.util.Properties()
if (keystorePropertiesFile.exists()) {
    keystorePropertiesFile.inputStream().use { keystoreProperties.load(it) }
}
val requiredSigningFields = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
val missingSigningFields =
    if (keystorePropertiesFile.exists()) {
        requiredSigningFields.filter { keystoreProperties.getProperty(it).isNullOrBlank() }
    } else {
        requiredSigningFields
    }
val hasReleaseSigning = keystorePropertiesFile.exists() && missingSigningFields.isEmpty()

val missingSigningMessage =
    buildString {
        appendLine("Release build 缺少正式簽章設定，已中止（不會退回 debug 金鑰）。")
        appendLine()
        if (!keystorePropertiesFile.exists()) {
            appendLine("找不到檔案：${keystorePropertiesFile.absolutePath}")
        } else {
            appendLine("檔案 ${keystorePropertiesFile.absolutePath} 缺少欄位：")
            appendLine("  " + missingSigningFields.joinToString(", "))
        }
        appendLine()
        appendLine("請建立／補齊該檔（已被 android/.gitignore 忽略，不要 commit）：")
        appendLine("  storeFile=/absolute/path/to/gu-voice-upload.jks")
        appendLine("  storePassword=<keystore 密碼>")
        appendLine("  keyAlias=upload")
        appendLine("  keyPassword=<key 密碼>")
        appendLine()
        appendLine("尚未有 keystore 時先產生一組（.jks 請離庫保管並備份，遺失就無法再更新已上架的 App）：")
        appendLine("  keytool -genkey -v -keystore /absolute/path/to/gu-voice-upload.jks \\")
        appendLine("      -storetype JKS -keyalg RSA -keysize 2048 -validity 10000 -alias upload")
        appendLine()
        append("debug / profile build 不需要這個檔，只有 release 需要。")
    }

// 守衛放在 task 層而不是 configuration 層：configuration 每次 build 都會跑，
// 在那裡 throw 會連 debug / profile build 一起擋掉。
if (!hasReleaseSigning) {
    val releaseArtifactPrefixes = listOf("assemble", "bundle", "package", "install")
    tasks.configureEach {
        val producesReleaseArtifact =
            name.contains("Release") && releaseArtifactPrefixes.any { name.startsWith(it) }
        if (producesReleaseArtifact) {
            doFirst { throw GradleException(missingSigningMessage) }
        }
    }
}

android {
    namespace = "com.guvoice.gu_voice"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.guvoice.gu_voice"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        // 只有在 key.properties 齊全時才建立;不齊全時刻意不建立,讓 release
        // buildType 維持沒有 signingConfig(而不是借用 debug 的)。
        if (hasReleaseSigning) {
            create("release") {
                storeFile = keystoreProperties.getProperty("storeFile")?.let { file(it) }
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            // 沒有正式簽章時不指定 signingConfig,並由上面的 task 守衛讓 build 失敗。
        }
    }
}

flutter {
    source = "../.."
}
