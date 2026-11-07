// MilestonesView.swift
// Beacon
//
// Development history: one card per milestone with its four-image gallery, the summary and the
// concrete changes. Screenshots disappear after seven days; the text stays.

import SwiftUI

struct MilestonesView: View {
    @EnvironmentObject private var model: AppModel
    @State private var viewer: ViewerContext?
    @State private var expanded: Set<String> = []

    private var columns: [GridItem] {
        [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: Theme.spacing) {
                    if model.milestones.isEmpty {
                        EmptyState(
                            symbol: "square.grid.2x2",
                            title: "No milestones yet",
                            message: "Milestones recorded by the agent appear here with their screenshots."
                        )
                        .beaconCard()
                    } else {
                        ForEach(model.milestones) { milestone in
                            card(for: milestone)
                        }
                        Text("Screenshots are kept for 7 days and removed automatically. Milestone summaries are permanent.")
                            .font(.beaconTiny)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.top, 4)
                    }
                }
                .padding(Theme.screenPadding)
                .padding(.bottom, 20)
            }
            .beaconScreen()
            .refreshable { await model.refreshMilestones() }
            .navigationTitle("Progress")
            .sheet(item: $viewer) { context in
                ScreenshotViewer(
                    milestoneTitle: context.milestoneTitle,
                    screenshots: context.screenshots,
                    startIndex: context.index
                )
            }
        }
    }

    private func card(for milestone: Milestone) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                StatusPill(text: "MILESTONE \(milestone.seq)", tone: .accent, compact: true)
                if !milestone.phase.isEmpty {
                    Text(milestone.phase)
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(Format.dayAndTime(milestone.createdAt))
                    .font(.beaconTiny)
                    .foregroundStyle(.secondary)
            }

            Text(milestone.title)
                .font(.beaconTitle)
                .fixedSize(horizontal: false, vertical: true)

            if !milestone.summary.isEmpty {
                Text(milestone.summary)
                    .font(.beaconBody)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if milestone.screenshots.isEmpty {
                VStack(spacing: 6) {
                    Image(systemName: "clock.badge.xmark")
                        .foregroundStyle(.secondary)
                    Text("Screenshots expired after 7 days")
                        .font(.beaconTiny)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(Theme.surfaceElevated, in: RoundedRectangle(cornerRadius: Theme.innerRadius, style: .continuous))
            } else {
                LazyVGrid(columns: columns, spacing: 8) {
                    ForEach(Array(milestone.screenshots.prefix(4).enumerated()), id: \.element.id) { index, shot in
                        AsyncScreenshot(
                            id: shot.id,
                            caption: shot.caption,
                            height: 132,
                            loader: { id in try await model.screenshotData(id: id) }
                        )
                        .contentShape(Rectangle())
                        .onTapGesture {
                            viewer = ViewerContext(
                                milestoneTitle: milestone.title,
                                screenshots: milestone.screenshots,
                                index: index
                            )
                        }
                    }
                }
            }

            if !milestone.changes.isEmpty {
                DisclosureGroup(
                    isExpanded: Binding(
                        get: { expanded.contains(milestone.id) },
                        set: { isOpen in
                            if isOpen { expanded.insert(milestone.id) } else { expanded.remove(milestone.id) }
                        }
                    )
                ) {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(milestone.changes, id: \.self) { change in
                            HStack(alignment: .top, spacing: 6) {
                                Text("·")
                                    .font(.beaconBody)
                                    .foregroundStyle(.secondary)
                                Text(change)
                                    .font(.beaconTiny)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(.top, 6)
                } label: {
                    Text("What changed (\(milestone.changes.count))")
                        .font(.beaconCaption)
                        .foregroundStyle(Theme.accent)
                }
            }

            if milestone.expiredScreenshots > 0 {
                InlineNote(
                    text: "\(milestone.expiredScreenshots) screenshot(s) removed by the 7-day retention policy.",
                    symbol: "clock.badge.xmark"
                )
            }
        }
        .beaconCard()
    }
}
