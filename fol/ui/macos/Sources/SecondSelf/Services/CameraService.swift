import AVFoundation
import AppKit

/// Captures the front camera feed and provides CGImage frames.
/// Used to show a live camera feed in the Dynamic Island notch area.
@MainActor
final class CameraService: NSObject, ObservableObject {
    @Published var currentFrame: CGImage?
    @Published var isRunning = false

    private var captureSession: AVCaptureSession?
    private var videoOutput: AVCaptureVideoDataOutput?
    private let sessionQueue = DispatchQueue(label: "com.fol.camera")
    private let outputQueue = DispatchQueue(label: "com.fol.camera.output")

    func startCapture() {
        guard !isRunning else { return }

        // Request camera permission
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            guard let self, granted else { return }
            Task { @MainActor in
                self.setupCaptureSession()
                self.captureSession?.startRunning()
                self.isRunning = true
            }
        }
    }

    func stopCapture() {
        sessionQueue.async { [weak self] in
            self?.captureSession?.stopRunning()
        }
        Task { @MainActor in
            self.isRunning = false
            self.currentFrame = nil
        }
    }

    private func setupCaptureSession() {
        let session = AVCaptureSession()
        session.sessionPreset = .low // Low res for small notch display

        // Select front camera
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
              let input = try? AVCaptureDeviceInput(device: device) else {
            print("FOL: No front camera available")
            return
        }

        if session.canAddInput(input) {
            session.addInput(input)
        }

        let output = AVCaptureVideoDataOutput()
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        ]
        output.setSampleBufferDelegate(self, queue: outputQueue)
        output.alwaysDiscardsLateVideoFrames = true

        if session.canAddOutput(output) {
            session.addOutput(output)
        }

        self.captureSession = session
        self.videoOutput = output
    }
}

extension CameraService: AVCaptureVideoDataOutputSampleBufferDelegate {
    nonisolated func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)

        // Crop to square (center crop)
        let extent = ciImage.extent
        let side = min(extent.width, extent.height)
        let cropped = ciImage.cropped(to: CGRect(
            x: (extent.width - side) / 2,
            y: (extent.height - side) / 2,
            width: side,
            height: side,
        ))

        let context = CIContext(options: [.useSoftwareRenderer: false])
        guard let cgImage = context.createCGImage(cropped, from: cropped.extent) else { return }

        Task { @MainActor in
            self.currentFrame = cgImage
        }
    }
}
