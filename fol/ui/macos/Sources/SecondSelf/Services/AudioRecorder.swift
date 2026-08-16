import Foundation
import AVFoundation

/// Manages audio recording using AVFoundation on macOS.
/// Records to a temporary WAV file and provides the file URL.
@MainActor
final class AudioRecorder: NSObject {
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var recordingTimer: Timer?

    /// Whether a recording is currently in progress
    private(set) var isRecording = false

    /// Recording duration in seconds
    private(set) var recordingDuration: TimeInterval = 0

    /// Start recording audio
    func startRecording() async -> Bool {
        // Check current permission status first
        let status = AVCaptureDevice.authorizationStatus(for: .audio)
        if status == .notDetermined {
            // Request permission
            let granted = await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    continuation.resume(returning: granted)
                }
            }
            guard granted else { return false }
        } else if status == .denied || status == .restricted {
            return false
        }

        // Create temp file URL
        let tempDir = FileManager.default.temporaryDirectory
        let fileURL = tempDir.appendingPathComponent("fol_voice_\(UUID().uuidString.prefix(8)).wav")

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]

        do {
            recorder = try AVAudioRecorder(url: fileURL, settings: settings)
            recorder?.delegate = self
            recorder?.isMeteringEnabled = true
            recordingURL = fileURL
            recordingDuration = 0

            let started = recorder?.record(forDuration: 60) ?? false
            if started {
                isRecording = true
                startDurationTimer()
            }
            return started
        } catch {
            print("FOL Recorder error: \(error)")
            return false
        }
    }

    /// Stop recording and return the audio file URL
    func stopRecording() -> URL? {
        guard isRecording else { return nil }

        stopDurationTimer()
        recorder?.stop()
        isRecording = false

        let duration = recordingDuration
        recordingDuration = 0

        // Too short — discard
        guard duration >= 0.5 else {
            cleanUpTempFile()
            return nil
        }

        let url = recordingURL
        recordingURL = nil
        recorder = nil
        return url
    }

    /// Cancel recording and discard the file
    func cancelRecording() {
        recorder?.stop()
        stopDurationTimer()
        isRecording = false
        recordingDuration = 0
        cleanUpTempFile()
    }

    // MARK: - Private

    private func startDurationTimer() {
        recordingTimer?.invalidate()
        recordingTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRecording else { return }
                self.recordingDuration += 0.1

                // Auto-stop at 60 seconds
                if self.recordingDuration >= 60 {
                    _ = self.stopRecording()
                }
            }
        }
    }

    private func stopDurationTimer() {
        recordingTimer?.invalidate()
        recordingTimer = nil
    }

    private func cleanUpTempFile() {
        if let url = recordingURL {
            try? FileManager.default.removeItem(at: url)
            recordingURL = nil
        }
        recorder = nil
    }
}

extension AudioRecorder: AVAudioRecorderDelegate {
    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor in
            self.isRecording = false
            self.stopDurationTimer()
        }
    }

    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        Task { @MainActor in
            self.isRecording = false
            self.stopDurationTimer()
            self.cleanUpTempFile()
        }
    }
}
