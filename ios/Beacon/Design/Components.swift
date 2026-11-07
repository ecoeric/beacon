// Components.swift
// Beacon
//
// Reusable, deliberately small building blocks. Every screen is composed from these so the
// visual language stays identical: cards, pills, metric tiles, key/value rows, banners.

import SwiftUI
import UIKit

// MARK: - Pills

struct StatusPill: View {
    let text: String
    var tone: Tone = .neutral
    var symbol: String? = nil
    var compact = false

    var body: some View {
        HStack(spacing: 5) {
            if let symbol {
                Image(systemName: symbol)
                    .font(.system(size: compact ? 9 : 10, weight: .bold))
            }
            Text(text)
                .font(compact ? .beaconTiny : .beaconCaption)
        }
        .foregroundStyle(Theme.colour(for: tone))
        .padding(.horizontal, compact ? 8 : 10)
        .padding(.vertical, compact ? 3 : 5)
        .background(Theme.colour(for: tone).opacity(0.13), in: Capsule())
        .accessibilityElement(children: .combine)
    }
}

struct MetaText: View {
    let text: String
    var symbol: String? = nil

    var body: some View {
        HStack(spacing: 4) {
            if let symbol {
                Image(systemName: symbol).font(.system(size: 10, weight: .medium))
            }
            Text(text)
        }
        .font(.beaconTiny)
        .foregroundStyle(.secondary)
    }
}

// MARK: - Structure

struct SectionHeader: View {
    let title: String
    var subtitle: String? = nil
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.beaconHeadline)
                    .foregroundStyle(.primary)
                if let subtitle {
                    Text(subtitle)
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .font(.beaconCaption)
                    .foregroundStyle(Theme.accent)
                    .buttonStyle(.plain)
            }
        }
    }
}

struct KeyValueRow: View {
    let label: String
    let value: String
    var mono = false
    var valueTone: Tone? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .font(.beaconBody)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            Text(value)
                .font(mono ? .beaconMono : .beaconBody)
                .foregroundStyle(valueTone.map(Theme.colour(for:)) ?? Color.primary)
                .multilineTextAlignment(.trailing)
        }
        .padding(.vertical, 3)
    }
}

struct DividerLine: View {
    var body: some View {
        Rectangle()
            .fill(Theme.separator)
            .frame(height: 0.7)
            .padding(.vertical, 6)
    }
}

// MARK: - Metrics

struct MetricTile: View {
    let title: String
    let value: String
    var detail: String? = nil
    var fraction: Double? = nil
    var tone: Tone = .accent

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .tracking(0.6)
            Text(value)
                .font(.beaconNumber)
                .foregroundStyle(.primary)
                .minimumScaleFactor(0.7)
                .lineLimit(1)
            if let fraction {
                ProgressTrack(fraction: fraction, tone: tone)
            }
            if let detail {
                Text(detail)
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
    }
}

struct ProgressTrack: View {
    let fraction: Double
    var tone: Tone = .accent

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.separator)
                Capsule()
                    .fill(Theme.colour(for: tone))
                    .frame(width: max(3, geometry.size.width * min(max(fraction, 0), 1)))
            }
        }
        .frame(height: 5)
        .accessibilityHidden(true)
    }
}

// MARK: - Banners and empty states

struct ErrorBanner: View {
    let message: String
    var retry: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Theme.warning)
                .font(.system(size: 14, weight: .semibold))
            VStack(alignment: .leading, spacing: 4) {
                Text(message)
                    .font(.beaconBody)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
                if let retry {
                    Button("Try again", action: retry)
                        .font(.beaconCaption)
                        .foregroundStyle(Theme.accent)
                        .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(Theme.warning.opacity(0.10), in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
    }
}

struct EmptyState: View {
    let symbol: String
    let title: String
    var message: String? = nil

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .regular))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.beaconHeadline)
                .multilineTextAlignment(.center)
            if let message {
                Text(message)
                    .font(.beaconBody)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 22)
    }
}

struct InlineNote: View {
    let text: String
    var symbol = "info.circle"

    var body: some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.secondary)
                .padding(.top, 1)
            Text(text)
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }
}

// MARK: - Activity

struct ActivityRow: View {
    let item: ActivityItem

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(Theme.colour(for: item.tone))
                .frame(width: 7, height: 7)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title)
                    .font(.beaconBody)
                    .foregroundStyle(item.isRead ? Color.secondary : Color.primary)
                    .lineLimit(2)
                if !item.body.isEmpty {
                    Text(item.body)
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 8)
            Text(Format.age(item.createdAt))
                .font(.beaconTiny)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Screenshots

/// Snapshot tests render synchronously, so images fetched ahead of time can be injected here.
enum AsyncScreenshotCache {
    static var images: [String: UIImage] = [:]
}

struct AsyncScreenshot: View {
    let id: String
    let caption: String
    var height: CGFloat = 150
    let loader: (String) async throws -> Data

    @State private var image: UIImage?
    @State private var failed = false
    @State private var loading = true

    /// Synchronous lookup so `ImageRenderer` snapshots can show real images.
    private var displayImage: UIImage? {
        image ?? AsyncScreenshotCache.images[id]
    }

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous)
                .fill(Theme.surfaceElevated)
            if let displayImage {
                Image(uiImage: displayImage)
                    .resizable()
                    .scaledToFill()
                    .frame(maxWidth: .infinity)
                    .frame(height: height)
                    .clipped()
            } else if failed {
                VStack(spacing: 6) {
                    Image(systemName: "photo.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                    Text("Unavailable")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if loading {
                ProgressView().controlSize(.small)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            LinearGradient(
                colors: [.clear, .black.opacity(0.62)],
                startPoint: .center,
                endPoint: .bottom
            )
            .allowsHitTesting(false)
            Text(caption)
                .font(.beaconTiny)
                .foregroundStyle(.white)
                .lineLimit(2)
                .padding(8)
        }
        .frame(height: height)
        .clipShape(RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous)
                .strokeBorder(Theme.separator, lineWidth: 0.8)
        )
        .task(id: id) {
            if image != nil { return }
            if AsyncScreenshotCache.images[id] != nil { loading = false; return }
            loading = true
            failed = false
            do {
                let data = try await loader(id)
                if let uiImage = UIImage(data: data) {
                    image = uiImage
                } else {
                    failed = true
                }
            } catch {
                failed = true
            }
            loading = false
        }
        .accessibilityLabel(caption)
    }
}

// MARK: - Small helpers

struct LoadingCard: View {
    var lines = 3

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(0..<lines, id: \.self) { index in
                RoundedRectangle(cornerRadius: 6)
                    .fill(Theme.separator)
                    .frame(height: index == 0 ? 14 : 10)
                    .frame(maxWidth: index == 0 ? 150 : .infinity, alignment: .leading)
            }
        }
        .redacted(reason: .placeholder)
        .beaconCard()
    }
}
