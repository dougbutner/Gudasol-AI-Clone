import AppKit
import Foundation
import Vision

func detect(url: URL) -> [String: Any] {
    guard let image = NSImage(contentsOf: url),
          let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let cg = bitmap.cgImage
    else {
        return ["file": url.lastPathComponent, "width": 0, "height": 0, "faces": [], "humans": []]
    }
    let width = Double(cg.width)
    let height = Double(cg.height)
    func boxes(from observations: [VNDetectedObjectObservation]) -> [[String: Double]] {
        observations.map { obs in
            let r = obs.boundingBox
            return [
                "x": r.origin.x * width,
                "y": (1.0 - r.origin.y - r.height) * height,
                "w": r.width * width,
                "h": r.height * height,
                "conf": Double(obs.confidence),
            ]
        }.sorted { ($0["w"]! * $0["h"]!) > ($1["w"]! * $1["h"]!) }
    }

    let faceReq = VNDetectFaceRectanglesRequest()
    let bodyReq = VNDetectHumanRectanglesRequest()
    let handler = VNImageRequestHandler(cgImage: cg, orientation: .up, options: [:])
    do {
        try handler.perform([faceReq, bodyReq])
    } catch {
        return ["file": url.lastPathComponent, "width": width, "height": height, "faces": [], "humans": []]
    }
    return [
        "file": url.lastPathComponent,
        "width": width,
        "height": height,
        "faces": boxes(from: faceReq.results ?? []),
        "humans": boxes(from: bodyReq.results ?? []),
    ]
}

var paths: [String] = Array(CommandLine.arguments.dropFirst())
if paths.isEmpty {
    fputs("usage: detect_faces <image> [image...]\n", stderr)
    exit(2)
}

var files: [URL] = []
for p in paths {
    let url = URL(fileURLWithPath: p)
    var isDir: ObjCBool = false
    if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
        let kids = (try? FileManager.default.contentsOfDirectory(at: url, includingPropertiesForKeys: nil)) ?? []
        files += kids.filter { ["jpg", "jpeg", "png"].contains($0.pathExtension.lowercased()) }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    } else {
        files.append(url)
    }
}

var rows: [[String: Any]] = []
for url in files {
    rows.append(detect(url: url))
}

let data = try! JSONSerialization.data(withJSONObject: rows, options: [])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data("\n".utf8))
