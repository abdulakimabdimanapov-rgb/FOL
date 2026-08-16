import Foundation
import AVFoundation

// MARK: - Sound Synthesizer

/// Generates JARVIS / Iron Man style sound effects as WAV audio data.
/// No external files needed — sounds are synthesized in memory using Core Audio.
///
/// Sound designs:
/// - `activationChime`: Rising electronic sweep — like JARVIS system activation
/// - `confirmationChime`: Two-tone descending chime — like JARVIS confirming a command
/// - `hudClick`: Crisp short HUD interface click — like the Iron Man suit UI
enum SoundSynthesizer {

    // MARK: - Configuration

    private static let sampleRate: Double = 44100
    private static let bitsPerSample: UInt16 = 16
    private static let channels: UInt16 = 1

    // MARK: - Public API

    /// Rising activation chime — played when a task starts.
    /// Frequency sweeps from 440Hz (A4) → 880Hz (A5) over 250ms.
    /// Rich tone with subtle harmonics for a sci-fi JARVIS feel.
    static func activationChime() -> Data {
        let duration: Double = 0.28
        let numSamples = Int(sampleRate * duration)
        var samples = [Int16](repeating: 0, count: numSamples)

        for i in 0..<numSamples {
            let t = Double(i) / sampleRate
            let progress = t / duration // 0.0 → 1.0

            // Frequency sweep: 440Hz → 880Hz
            let freq = 440.0 + (440.0 * progress)

            // Envelope: smooth fade-in (15ms) + fade-out (40ms)
            let fadeIn = min(1.0, t / 0.015)
            let fadeOut = min(1.0, (duration - t) / 0.04)
            let envelope = fadeIn * fadeOut

            // Primary tone (fundamental)
            let fundamental = sin(2.0 * .pi * freq * t)

            // First harmonic (octave up) — adds richness
            let harmonic1 = 0.3 * sin(2.0 * .pi * freq * 2.0 * t)

            // Sub-harmonic (octave down) — adds body
            let subHarmonic = 0.15 * sin(2.0 * .pi * freq * 0.5 * t)

            let value = envelope * 0.6 * (fundamental + harmonic1 + subHarmonic)
            let clamped = max(-1.0, min(1.0, value))
            samples[i] = Int16(clamped * Double(Int16.max))
        }

        return makeWAV(samples: samples)
    }

    /// Two-tone descending confirmation chime — played when a task completes.
    /// First tone: 880Hz (A5) for 100ms
    /// Second tone: 660Hz (E5) for 120ms
    /// 15ms gap between tones. Sounds like JARVIS confirming "Command accepted."
    static func confirmationChime() -> Data {
        let totalDuration: Double = 0.28
        let numSamples = Int(sampleRate * totalDuration)
        var samples = [Int16](repeating: 0, count: numSamples)

        let tone1Start = 0.0
        let tone1End = 0.10
        let gapEnd = 0.115
        let tone2End = 0.235
        let tailEnd = totalDuration

        for i in 0..<numSamples {
            let t = Double(i) / sampleRate

            if t >= tone1Start && t < tone1End {
                // First tone: 880Hz (A5)
                let localT = t - tone1Start
                let localDuration = tone1End - tone1Start
                let env = min(1.0, localT / 0.008) * min(1.0, (localDuration - localT) / 0.012)
                let tone = sin(2.0 * .pi * 880.0 * t)
                // Add a subtle fifth above for richness
                let fifth = 0.25 * sin(2.0 * .pi * 1320.0 * t)
                let value = env * 0.55 * (tone + fifth)
                samples[i] = Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))

            } else if t >= gapEnd && t < tone2End {
                // Second tone: 660Hz (E5)
                let localT = t - gapEnd
                let localDuration = tone2End - gapEnd
                let env = min(1.0, localT / 0.008) * min(1.0, (localDuration - localT) / 0.02)
                let tone = sin(2.0 * .pi * 660.0 * t)
                let fifth = 0.2 * sin(2.0 * .pi * 990.0 * t)
                let value = env * 0.5 * (tone + fifth)
                samples[i] = Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))

            } else if t >= tone2End && t < tailEnd {
                // Subtle reverb tail — short fade
                let localT = t - tone2End
                let tailDuration = tailEnd - tone2End
                let env = max(0, 1.0 - localT / tailDuration)
                let reverb = 0.08 * sin(2.0 * .pi * 660.0 * t * 0.97) // slightly detuned decay
                let value = env * reverb
                samples[i] = Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))
            }
        }

        return makeWAV(samples: samples)
    }

    /// Grand JARVIS boot chime — played once on app launch.
    /// Slow ascending arpeggio: C4 → E4 → G4 → C5 over ~0.9s.
    /// Rich harmonics and long sustain — like JARVIS powering up the system.
    static func bootChime() -> Data {
        let duration: Double = 0.92
        let numSamples = Int(sampleRate * duration)
        var samples = [Int16](repeating: 0, count: numSamples)

        // Notes of the arpeggio: C4, E4, G4, C5
        let notes: [(freq: Double, start: Double, end: Double)] = [
            (261.63, 0.00, 0.22),  // C4
            (329.63, 0.20, 0.44),  // E4
            (392.00, 0.40, 0.66),  // G4
            (523.25, 0.60, 0.86),  // C5
        ]

        for i in 0..<numSamples {
            let t = Double(i) / sampleRate
            var value: Double = 0

            for (freq, start, end) in notes {
                guard t >= start && t < end else { continue }
                let localT = t - start
                let localDuration = end - start

                // Smooth attack (20ms) and release (40ms) for each note
                let attack = min(1.0, localT / 0.02)
                let release = min(1.0, (localDuration - localT) / 0.04)
                let envelope = attack * release

                // Fundamental
                let fundamental = sin(2.0 * .pi * freq * t)
                // Octave above — adds sparkle
                let octave = 0.3 * sin(2.0 * .pi * freq * 2.0 * t)
                // Fifth above — adds warmth
                let fifth = 0.15 * sin(2.0 * .pi * freq * 1.5 * t)

                value += envelope * 0.45 * (fundamental + octave + fifth)
            }

            // Global fade in/out for the whole chime
            let fadeIn = min(1.0, t / 0.04)
            let fadeOut = min(1.0, (duration - t) / 0.08)
            let globalEnvelope = fadeIn * fadeOut

            let clamped = max(-1.0, min(1.0, value * globalEnvelope))
            samples[i] = Int16(clamped * Double(Int16.max))
        }

        return makeWAV(samples: samples)
    }

    /// Recording start chime — quick two-tone rising "dut-dut".
    /// Played once when the user taps the mic to start recording.
    /// Tone 1: 600Hz square-ish attack (60ms)
    /// Tone 2: 900Hz with harmonics (90ms)
    /// Total ~170ms. Sounds like a camera or device starting to record.
    static func recordingChime() -> Data {
        let duration: Double = 0.17
        let numSamples = Int(sampleRate * duration)
        var samples = [Int16](repeating: 0, count: numSamples)

        let tone1Start = 0.0
        let tone1End = 0.06
        let gapEnd = 0.07
        let tone2End = 0.16

        for i in 0..<numSamples {
            let t = Double(i) / sampleRate

            if t >= tone1Start && t < tone1End {
                // First tone: 600Hz with sharp attack
                let localT = t - tone1Start
                let localDuration = tone1End - tone1Start
                let env = min(1.0, localT / 0.004) * min(1.0, (localDuration - localT) / 0.01)
                let tone = sin(2.0 * .pi * 600.0 * t)
                // Add a fifth for richness
                let fifth = 0.3 * sin(2.0 * .pi * 900.0 * t)
                let value = env * 0.5 * (tone + fifth)
                samples[i] = Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))

            } else if t >= gapEnd && t < tone2End {
                // Second tone: 900Hz with harmonics — slightly louder
                let localT = t - gapEnd
                let localDuration = tone2End - gapEnd
                let env = min(1.0, localT / 0.004) * min(1.0, (localDuration - localT) / 0.015)
                let fundamental = sin(2.0 * .pi * 900.0 * t)
                let octave = 0.35 * sin(2.0 * .pi * 1800.0 * t)
                let fifth = 0.2 * sin(2.0 * .pi * 1350.0 * t)
                let value = env * 0.55 * (fundamental + octave + fifth)
                samples[i] = Int16(max(-1.0, min(1.0, value)) * Double(Int16.max))
            }
        }

        return makeWAV(samples: samples)
    }

    /// Crisp HUD interface click — played every ~5 typing characters.
    /// Short 2kHz click with sharp attack and quick exponential decay.
    /// Mimics the holographic UI click from the Iron Man suit.
    static func hudClick() -> Data {
        let duration: Double = 0.018
        let numSamples = Int(sampleRate * duration)
        var samples = [Int16](repeating: 0, count: numSamples)

        for i in 0..<numSamples {
            let t = Double(i) / sampleRate
            let progress = t / duration

            // Sharp attack, exponential decay
            let envelope = exp(-progress * 12.0)

            // Mix of high frequencies for a crisp click
            let tone1 = sin(2.0 * .pi * 2400.0 * t)
            let tone2 = 0.5 * sin(2.0 * .pi * 3600.0 * t)
            let noise = 0.3 * Double.random(in: -1.0...1.0) // tiny noise burst for texture

            let value = envelope * 0.5 * (tone1 + tone2 + noise)
            let clamped = max(-1.0, min(1.0, value))
            samples[i] = Int16(clamped * Double(Int16.max))
        }

        return makeWAV(samples: samples)
    }

    // MARK: - WAV Generation

    /// Build a WAV file from 16-bit mono PCM samples.
    /// Returns Data with proper RIFF/WAV headers ready for AVAudioPlayer.
    private static func makeWAV(samples: [Int16]) -> Data {
        var data = Data()

        let numChannels: UInt16 = channels
        let sampleRate = UInt32(Self.sampleRate)
        let bitsPerSample = Self.bitsPerSample
        let bytesPerSample = bitsPerSample / 8
        let blockAlign = numChannels * bytesPerSample
        let byteRate = sampleRate * UInt32(blockAlign)
        let dataSize = UInt32(samples.count) * UInt32(bytesPerSample)
        let fileSize = 36 + dataSize // total file size - 8

        // --- RIFF header ---
        data.append(contentsOf: [0x52, 0x49, 0x46, 0x46]) // "RIFF"
        data.append(contentsOf: fileSize.littleEndianBytes)
        data.append(contentsOf: [0x57, 0x41, 0x56, 0x45]) // "WAVE"

        // --- fmt chunk ---
        data.append(contentsOf: [0x66, 0x6D, 0x74, 0x20]) // "fmt "
        data.append(contentsOf: UInt32(16).littleEndianBytes) // chunk size
        data.append(contentsOf: UInt16(1).littleEndianBytes) // PCM format
        data.append(contentsOf: numChannels.littleEndianBytes)
        data.append(contentsOf: sampleRate.littleEndianBytes)
        data.append(contentsOf: byteRate.littleEndianBytes)
        data.append(contentsOf: blockAlign.littleEndianBytes)
        data.append(contentsOf: bitsPerSample.littleEndianBytes)

        // --- data chunk ---
        data.append(contentsOf: [0x64, 0x61, 0x74, 0x61]) // "data"
        data.append(contentsOf: dataSize.littleEndianBytes)

        // --- PCM samples (cast Int16 → UInt16 for little-endian serialization) ---
        for sample in samples {
            data.append(contentsOf: UInt16(bitPattern: sample).littleEndianBytes)
        }

        return data
    }
}

// MARK: - Little-Endian Helpers

private extension UInt16 {
    /// 2 bytes in little-endian order.
    var littleEndianBytes: [UInt8] {
        [UInt8(self & 0xFF), UInt8((self >> 8) & 0xFF)]
    }
}

private extension UInt32 {
    /// 4 bytes in little-endian order.
    var littleEndianBytes: [UInt8] {
        [
            UInt8(self & 0xFF),
            UInt8((self >> 8) & 0xFF),
            UInt8((self >> 16) & 0xFF),
            UInt8((self >> 24) & 0xFF),
        ]
    }
}
