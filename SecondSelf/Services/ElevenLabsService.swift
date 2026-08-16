import Foundation
import os

// MARK: - ElevenLabs Service

/// Client for ElevenLabs APIs. STT + TTS.
/// Reads ELEVENLABS_API_KEY from the app's .env vars (exposed via AppDelegate.sharedEnvVars).
final class ElevenLabsService: @unchecked Sendable {

    // MARK: - JARVIS Voice Configuration

    /// Voice ID for "George" — the most JARVIS-like British male voice in ElevenLabs.
    /// Warm, crisp baritone with calm, intelligent delivery — identical to Paul Bettany's JARVIS.
    static let jarvisVoiceID = "JBFqnCBsd6RMkjVDRZzb"

    /// TTS model: multilingual v2 for best accent stability and realism.
    private static let ttsModel = "eleven_multilingual_v2"

    /// TTS endpoint: POST /v1/text-to-speech/{voice_id}
    private static func ttsEndpoint(voiceID: String) -> URL {
        URL(string: "https://api.elevenlabs.io/v1/text-to-speech/\(voiceID)")!
    }

    // MARK: - TTS (Text to Speech)

    enum TTSError: LocalizedError {
        case noAPIKey
        case networkError(Error)
        case authError
        case emptyText
        case timeout
        case serverError(Int, String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey: return "No ElevenLabs API key configured"
            case .networkError(let e): return "Network error: \(e.localizedDescription)"
            case .authError: return "Invalid API key"
            case .emptyText: return "No text to speak"
            case .timeout: return "TTS timed out"
            case .serverError(let code, let msg): return "Server error \(code): \(msg)"
            }
        }
    }

    /// Speak text using ElevenLabs TTS with the JARVIS voice profile.
    /// - Parameter text: The text to synthesize.
    /// - Parameter voiceID: ElevenLabs voice ID. Defaults to JARVIS voice.
    /// - Returns: Audio data (MP3 format) ready for playback.
    func speak(text: String, voiceID: String = ElevenLabsService.jarvisVoiceID) async throws -> Data {
        guard let apiKey else {
            throw TTSError.noAPIKey
        }

        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw TTSError.emptyText
        }

        logger.info("TTS: saying \(trimmed.count) chars with voice \(voiceID.prefix(8))...")

        // Build request body
        let body: [String: Any] = [
            "text": trimmed,
            "model_id": Self.ttsModel,
            "voice_settings": [
                "stability": 0.7,       // Steady, calm — no emotional fluctuation
                "similarity_boost": 0.75, // Good clone fidelity
                "style": 0.1,            // Minimal style exaggeration — flat, JARVIS-like
                "use_speaker_boost": true
            ]
        ]

        var request = URLRequest(url: Self.ttsEndpoint(voiceID: voiceID))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 30

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            logger.error("TTS request timed out")
            throw TTSError.timeout
        } catch {
            logger.error("TTS network error: \(error.localizedDescription)")
            throw TTSError.networkError(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw TTSError.networkError(URLError(.badServerResponse))
        }

        switch httpResponse.statusCode {
        case 200:
            logger.info("TTS: received \(data.count) bytes of audio")
            return data
        case 401:
            logger.error("TTS auth failed (401)")
            throw TTSError.authError
        default:
            let body = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("TTS failed \(httpResponse.statusCode): \(body)")
            throw TTSError.serverError(httpResponse.statusCode, body)
        }
    }

    // MARK: - STT Error

    enum STTError: LocalizedError {
        case noAPIKey
        case networkError(Error)
        case authError
        case emptyTranscription
        case timeout
        case serverError(Int, String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey: return "No ElevenLabs API key configured"
            case .networkError(let e): return "Network error: \(e.localizedDescription)"
            case .authError: return "Invalid API key"
            case .emptyTranscription: return "Nothing heard"
            case .timeout: return "Transcription timed out"
            case .serverError(let code, let msg): return "Server error \(code): \(msg)"
            }
        }
    }

    private static let sttEndpoint = URL(string: "https://api.elevenlabs.io/v1/speech-to-text")!
    private static let model = "scribe_v1"
    private static let timeoutSeconds: TimeInterval = 30

    private let logger = Logger(subsystem: "com.secondself.app", category: "ElevenLabs")

    /// Whether an API key is available in .env.
    var hasAPIKey: Bool {
        apiKey != nil
    }

    private var apiKey: String? {
        let key = AppDelegate.sharedEnvVars["ELEVENLABS_API_KEY"]
        guard let key, !key.isEmpty else { return nil }
        return key
    }

    // MARK: - Speech to Text

    /// Transcribe an audio file using ElevenLabs Scribe.
    /// - Parameter fileURL: Path to a WAV audio file (16kHz mono PCM).
    /// - Returns: The transcribed text.
    /// - Throws: `STTError` on failure.
    func transcribe(fileURL: URL) async throws -> String {
        guard let apiKey else {
            throw STTError.noAPIKey
        }

        let audioData: Data
        do {
            audioData = try Data(contentsOf: fileURL)
        } catch {
            throw STTError.networkError(error)
        }

        let languageCode = Self.detectedLanguage()
        logger.info("Transcribing \(audioData.count) bytes from \(fileURL.lastPathComponent) (lang: \(languageCode))")

        // Build multipart form body
        var form = MultipartFormData()
        form.addField(name: "model_id", value: Self.model)
        form.addField(name: "language_code", value: languageCode)
        form.addFile(name: "file", fileName: "recording.wav", mimeType: "audio/wav", data: audioData)
        form.finalize()

        // Build request
        var request = URLRequest(url: Self.sttEndpoint)
        request.httpMethod = "POST"
        request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.httpBody = form.data
        request.timeoutInterval = Self.timeoutSeconds

        // Send
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            logger.error("Request timed out")
            throw STTError.timeout
        } catch {
            logger.error("Network error: \(error.localizedDescription)")
            throw STTError.networkError(error)
        }

        // Parse response
        guard let httpResponse = response as? HTTPURLResponse else {
            throw STTError.networkError(URLError(.badServerResponse))
        }

        switch httpResponse.statusCode {
        case 200:
            break
        case 401:
            logger.error("Auth failed (401)")
            throw STTError.authError
        default:
            let body = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("STT failed \(httpResponse.statusCode): \(body)")
            throw STTError.serverError(httpResponse.statusCode, body)
        }

        // Extract text from response JSON
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let text = json["text"] as? String else {
            logger.error("Could not parse 'text' from response")
            throw STTError.emptyTranscription
        }

        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            throw STTError.emptyTranscription
        }

        logger.info("Transcription: \(trimmed.prefix(80))...")
        return trimmed
    }

    /// Auto-detect the user's preferred language from macOS system preferences.
    /// Uses the first language in the system's preferred languages list.
    /// Returns ISO 639-1 two-letter code (e.g., "ru", "en", "kk", "de", "fr").
    /// Falls back to "en" if detection fails.
    private static func detectedLanguage() -> String {
        let preferred = Locale.preferredLanguages.first ?? "en"
        // macOS 13+ API: Locale.language.languageCode.identifier gives ISO 639-1 code
        let code = Locale(identifier: preferred).language.languageCode?.identifier ?? "en"
        return code
    }
}
