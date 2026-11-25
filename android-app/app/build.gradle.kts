plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.tanglisp.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "org.tanglisp.companion"
        minSdk = 26
        targetSdk = 34
        versionCode = 10
        versionName = "0.6.4"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // FTDI (and other) USB serial drivers; the Tang dock's BL616 enumerates
    // as an FTDI FT2232 (VID 0x0403, PID 0x6010) with two serial ports.
    implementation("com.github.mik3y:usb-serial-for-android:3.8.1")
}
