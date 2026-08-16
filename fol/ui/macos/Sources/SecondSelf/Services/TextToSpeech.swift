import AppKit

/// Text-to-Speech service using macOS NSSpeechSynthesizer.
@MainActor
final class TextToSpeech: NSObject {
    private let synthesizer: NSSpeechSynthesizer
    private(set) var isSpeaking = false
    private(set) var currentVoiceName: String = "Daniel"
    private var completionHandler: (() -> Void)?

    /// All available macOS voices as (name, displayName) pairs
    static let availableVoices: [(name: String, display: String)] = {
        let rawVoices = NSSpeechSynthesizer.availableVoices
        return rawVoices.map { voiceID in
            let attrs = NSSpeechSynthesizer.attributes(forVoice: voiceID)
            let name = attrs[NSSpeechSynthesizer.VoiceAttributeKey.name] as? String ?? voiceID.rawValue
            // Display: "Name (Language)" e.g. "Daniel (en-GB)"
            let locale = attrs[NSSpeechSynthesizer.VoiceAttributeKey.localeIdentifier] as? String ?? ""
            let display = locale.isEmpty ? name : "\(name) (\(locale))"
            return (name, display)
        }
    }()

    override init() {
        self.synthesizer = NSSpeechSynthesizer()
        super.init()
        synthesizer.delegate = self
        // Set default voice
        setVoice("Daniel")
        synthesizer.rate = 160
        synthesizer.volume = 1.0
    }

    func speak(_ text: String, completion: (() -> Void)? = nil) {
        guard !text.isEmpty else { completion?(); return }
        stop()
        completionHandler = completion
        isSpeaking = true
        synthesizer.startSpeaking(text)
    }

    func stop() {
        synthesizer.stopSpeaking()
        isSpeaking = false
        completionHandler = nil
    }

    /// Set voice by name (e.g. "Daniel", "Samantha", "Alex", "Milena")
    @discardableResult
    func setVoice(_ name: String) -> Bool {
        let rawVoices = NSSpeechSynthesizer.availableVoices
        for voiceID in rawVoices {
            let attrs = NSSpeechSynthesizer.attributes(forVoice: voiceID)
            if let voiceName = attrs[NSSpeechSynthesizer.VoiceAttributeKey.name] as? String,
               voiceName == name {
                synthesizer.setVoice(voiceID)
                currentVoiceName = voiceName
                return true
            }
        }
        return false
    }

    func setRate(_ rate: Float) {
        synthesizer.rate = rate
    }
}

extension TextToSpeech: NSSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ sender: NSSpeechSynthesizer, didFinishSpeaking finishedSpeaking: Bool) {
        Task { @MainActor in
            self.isSpeaking = false
            self.completionHandler?()
            self.completionHandler = nil
        }
    }
}
