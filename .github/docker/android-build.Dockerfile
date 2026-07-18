# x86_64 Android build environment, run under QEMU emulation on the
# arm64 self-hosted runner -- Google does not publish a native
# linux-aarch64 aapt2 (checked directly against dl.google.com/maven2
# across every stable AGP release through 9.3.0; none exist), so the
# Android compile step runs inside this container instead of on the
# bare host. Versions pinned to match apps/mobile/android/build.gradle
# exactly -- do not bump independently of that file.
FROM --platform=linux/amd64 eclipse-temurin:17-jdk

ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends unzip curl && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p "${ANDROID_HOME}/cmdline-tools" && \
    curl -fsSL -o /tmp/cmdline-tools.zip \
      https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip && \
    unzip -q /tmp/cmdline-tools.zip -d "${ANDROID_HOME}/cmdline-tools" && \
    mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest" && \
    rm /tmp/cmdline-tools.zip && \
    yes | sdkmanager --licenses > /dev/null && \
    sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0" "ndk;27.1.12297006"

WORKDIR /workspace
