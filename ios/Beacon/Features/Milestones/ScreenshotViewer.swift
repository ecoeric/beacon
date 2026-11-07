// ScreenshotViewer.swift
// Beacon
//
// Full-size view of one milestone screenshot with its caption and retention metadata.
// Images are streamed from the server; nothing is cached permanently on the device.

import SwiftUI
import UIKit

struct ScreenshotViewer: View {
    let milestoneTitle: String
    let screenshots: [ScreenshotMeta]
    let startIndex: Int

    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var index: Int
    @State private var image: UIImage?
    @State private var failed = false

    init(milestoneTitle: String, screenshots: [ScreenshotMeta], startIndex: Int) {
        self.milestoneTitle = milestoneTitle
        self.screenshots = screenshots
        self.startIndex = startIndex
        _index = State(initialValue: max(0, min(startIndex, max(0, screenshots.count - 1))))
    }

    private var current: ScreenshotMeta? {
        guard screenshots.indices.contains(index) else { return nil }
        return screenshots[index]
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ZStack {
                    Color.black.opacity(0.92)
                    if let image {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFit()
                            .padding(8)
                    } else if failed {
                        EmptyState(
                            symbol: "photo.badge.exclamationmark",
                            title: "Image unavailable",
                            message: "It may have passed the 7-day retention window."
                        )
                        .foregroundStyle(.white)
                    } else {
                        ProgressView().tint(.white)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                metadata
            }
            .background(Theme.background)
            .navigationTitle(milestoneTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
                if screenshots.count > 1 {
                    ToolbarItemGroup(placement: .bottomBar) {
                        Button {
                            index = max(0, index - 1)
                        } label: {
                            Image(systemName: "chevron.left")
                        }
                        .disabled(index == 0)
                        Spacer()
                        Text("\(index + 1) of \(screenshots.count)")
                            .font(.beaconCaption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button {
                            index = min(screenshots.count - 1, index + 1)
                        } label: {
                            Image(systemName: "chevron.right")
                        }
                        .disabled(index == screenshots.count - 1)
                    }
                }
            }
        }
        .task(id: index) {
            guard let current else { return }
            image = nil
            failed = false
            do {
                let data = try await model.screenshotData(id: current.id)
                image = UIImage(data: data)
                if image == nil { failed = true }
            } catch {
                failed = true
            }
        }
    }

    @ViewBuilder
    private var metadata: some View {
        if let current {
            VStack(alignment: .leading, spacing: 6) {
                if !current.caption.isEmpty {
                    Text(current.caption)
                        .font(.beaconBody)
                        .foregroundStyle(.primary)
                }
                HStack(spacing: 12) {
                    MetaText(
                        text: [current.width, current.height]
                            .compactMap { $0 }
                            .map(String.init)
                            .joined(separator: "×"),
                        symbol: "aspectratio"
                    )
                    MetaText(text: Format.bytes(current.bytes), symbol: "internaldrive")
                    MetaText(text: Format.dayAndTime(current.createdAt), symbol: "calendar")
                }
                Text(Format.expiry(current.expiresAt) + " · screenshots are deleted automatically after 7 days")
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Theme.screenPadding)
            .background(Theme.surface)
        }
    }
}
