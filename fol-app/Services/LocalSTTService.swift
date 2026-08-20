import Foundation
import os

// MARK: - Local STT Service

/// Transcribes audio through FOL's local backend (`POST /api/stt`), which
/// runs mlx-whisper on Apple Silicon — no API key required.
///
/// This is the fallback that makes the microphone work even without
/// OPENAI_API_KEY / ELEVENLABS_API_KEY (pure local / Ollama setups): the app
/// itself launches the FOL server on :8754 in local mode, so the mic must not
/// depend on paid cloud transcription keys.
final class LocalSTTService: @unchecked Sendable {

    enum STTError: LocalizedError {
        case backendUnreachable
        case emptyTranscription
        case localSTTUnavailable
        case serverError(Int, String)

        var errorDescription: String? {
            switch self {
            case .backendUnreachable:
                return "FOL speech service is not running"
            case .emptyTranscription:
                return "Nothing heard"
            case .localSTTUnavailable:
                return "Local speech recognition is not installed. Run 'pip install mlx-whisper' to enable offline voice input."
            case .serverError(let code, let msg):
                return "Speech service error \(code): \(msg)"
            }
        }
    }

    private let logger = Logger(subsystem: "com.secondself.app", category: "LocalSTT")

    /// Probe the FOL backend health endpoint. Retries for a few seconds
    /// because the app launches the server itself and it takes time to boot.
    static func backendReachable(retries: Int = 6, delay: TimeInterval = 2.0) async -> Bool {
        guard let url = URL(string: ServerConfig.folHealthEndpoint) else { return false }
        for attempt in 0..<max(1, retries) {
            var request = URLRequest(url: url)
            request.timeoutInterval = 2
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    return true
                }
            } catch {
                // server still booting — retry
            }
            if attempt < max(1, retries) - 1 {
                try? await Task.sleep(for: .seconds(delay))
            }
        }
        return false
    }

    /// Transcribe a WAV file via `POST /api/stt` (multipart form).
    func transcribe(fileURL: URL) async throws -> String {
        guard let url = URL(string: ServerConfig.folSTTEndpoint) else {
            throw STTError.backendUnreachable
        }
        let audioData: Data
        do {
            audioData = try Data(contentsOf: fileURL)
        } catch {
            throw STTError.backendUnreachable
        }

        let boundary = UUID().uuidString
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        // Local mlx-whisper transcription can take several seconds.
        request.timeoutInterval = 60

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw STTError.backendUnreachable
        }
        guard let http = response as? HTTPURLResponse else {
            throw STTError.backendUnreachable
        }
        guard http.statusCode == 200 else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw STTError.serverError(http.statusCode, msg)
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw STTError.emptyTranscription
        }
        // Surface the real reason (e.g. mlx-whisper missing) instead of
        // claiming the user said nothing.
        if let error = json["error"] as? String, error == "local_stt_unavailable" {
            throw STTError.localSTTUnavailable
        }
        guard let text = json["text"] as? String else {
            throw STTError.emptyTranscription
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            throw STTError.emptyTranscription
        }
        logger.info("Local STT transcription: \(trimmed.prefix(60))...")
        return trimmed
    }
}
