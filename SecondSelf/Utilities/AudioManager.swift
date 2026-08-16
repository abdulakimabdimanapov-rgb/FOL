import AppKit
import AVFoundation

// MARK: - Audio Manager

/// Manages JARVIS-style sound effects and TTS voice playback for the FOL app.
/// Sound effects are synthesised in memory (no external files needed) and
/// evoke the Iron Man / JARVIS interface — activation chimes, confirmation
/// tones, and crisp HUD clicks.
@MainActor
final class AudioManager: NSObject {
    /// Shared singleton — used by ChatViewModel and boot chime alike,
    /// so mute state is consistent across the app.
    static let shared = AudioManager()

    /// UserDefaults keys for persisting audio settings across launches.
    private static let mutedKey = "jarvisMuted"
    private static let volumeKey = "jarvisVolume"

    private var typingCounter: Int = 0
    private var ttsPlayer: AVAudioPlayer?
    private var sfxPlayer: AVAudioPlayer?

    /// When true, all audio output (TTS + sound effects) is silenced.
    /// Persisted to UserDefaults so the setting survives app restarts.
    var isMuted: Bool = false {
        didSet { UserDefaults.standard.set(isMuted, forKey: Self.mutedKey) }
    }

    /// Master volume 0.0–1.0 applied to both TTS and sound effects.
    /// Default 0.7. Persisted to UserDefaults.
    var volume: Float = 0.7 {
        didSet { UserDefaults.standard.set(volume, forKey: Self.volumeKey) }
    }

    /// Restore the persisted mute state. Call this on launch before playing any audio.
    func restoreMuteState() {
        isMuted = UserDefaults.standard.bool(forKey: Self.mutedKey)
        volume = UserDefaults.standard.float(forKey: Self.volumeKey)
        if volume == 0 { volume = 0.7 } // default on first launch
    }

    // MARK: - TTS Voice Playback

    /// Play TTS audio data (MP3 from ElevenLabs) through the speakers.
    /// Stops any previous playback first to prevent overlap.
    /// Does nothing if muted. Respects master volume.
    func playTTSAudio(data: Data) {
        guard !isMuted else { return }
        ttsPlayer?.stop()
        ttsPlayer = nil
        do {
            let player = try AVAudioPlayer(data: data)
            player.delegate = self
            player.volume = volume
            player.prepareToPlay()
            player.play()
            ttsPlayer = player
        } catch {
            print("[AudioManager] Failed to play TTS audio: \(error)")
        }
    }

    /// Stop TTS playback if currently playing.
    func stopTTS() {
        ttsPlayer?.stop()
        ttsPlayer = nil
    }

    /// Whether TTS audio is currently playing.
    var isTTSPlaying: Bool {
        ttsPlayer?.isPlaying ?? false
    }

    /// Stop all audio (TTS + SFX) immediately.
    func stopAll() {
        stopTTS()
        sfxPlayer?.stop()
        sfxPlayer = nil
    }

    // MARK: - JARVIS Sound Effects

    /// JARVIS boot chime — slow grand ascending arpeggio.
    /// Played once when the app launches.
    /// Does nothing if muted.
    func playBootChime() {
        guard !isMuted else { return }
        playSFX(SoundSynthesizer.bootChime(), baseLevel: 0.45)
    }

    /// JARVIS activation chime — rising electronic sweep.
    /// Played when the Twin starts processing a task.
    /// Does nothing if muted.
    func playTaskStart() {
        guard !isMuted else { return }
        playSFX(SoundSynthesizer.activationChime(), baseLevel: 0.35)
    }

    /// JARVIS confirmation chime — two-tone descending "bwoop-bwoop".
    /// Played when the Twin completes a task.
    /// Does nothing if muted.
    func playCompletion() {
        guard !isMuted else { return }
        playSFX(SoundSynthesizer.confirmationChime(), baseLevel: 0.4)
    }

    /// Recording start chime — quick two-tone rising "dut-dut".
    /// Played once when the user taps the mic to start recording.
    /// Does nothing if muted.
    func playRecordingChime() {
        guard !isMuted else { return }
        playSFX(SoundSynthesizer.recordingChime(), baseLevel: 0.4)
    }

    /// Iron Man HUD click — crisp high-frequency tap.
    /// Called every ~5th character for typing feel.
    /// Does nothing if muted.
    func playTypingClick() {
        guard !isMuted else { return }
        playSFX(SoundSynthesizer.hudClick(), baseLevel: 0.25)
    }

    /// Increment the typing counter and play a click every 5th character.
    func incrementTypingCounter() {
        guard !isMuted else { return }
        typingCounter += 1
        if typingCounter % 5 == 0 {
            playTypingClick()
        }
    }

    /// Reset the typing counter (e.g., when a new message starts).
    func resetTypingCounter() {
        typingCounter = 0
    }

    // MARK: - Private

    /// Play a synthesised sound effect, stopping any previous SFX first.
    /// Final volume = baseLevel * masterVolume (so slider scales all sounds).
    private func playSFX(_ data: Data, baseLevel: Float) {
        sfxPlayer?.stop()
        do {
            let player = try AVAudioPlayer(data: data)
            player.volume = baseLevel * volume
            player.prepareToPlay()
            player.play()
            sfxPlayer = player
        } catch {
            print("[AudioManager] Failed to play SFX: \(error)")
        }
    }
}

// MARK: - AVAudioPlayerDelegate

extension AudioManager: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.ttsPlayer = nil
        }
    }
}
