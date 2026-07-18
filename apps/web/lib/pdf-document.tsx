import {
  Document,
  Link,
  Page,
  StyleSheet,
  Text,
  View,
} from "@react-pdf/renderer";
import type { Report, Run } from "./types";

const RISK_COLORS: Record<string, string> = {
  high: "#C0392B",
  moderate: "#B9770E",
  low: "#1E8449",
  none: "#566573",
  info: "#566573",
};

const styles = StyleSheet.create({
  page: { padding: 48, fontSize: 9.5, color: "#1C2833", lineHeight: 1.5 },
  header: { marginBottom: 18, borderBottom: "2 solid #0B0F14", paddingBottom: 12 },
  brand: { fontSize: 10, color: "#148F66", marginBottom: 6, letterSpacing: 1 },
  title: { fontSize: 18, fontWeight: 700, marginBottom: 4 },
  meta: { fontSize: 8.5, color: "#566573" },
  h2: { fontSize: 12, fontWeight: 700, marginTop: 14, marginBottom: 6, color: "#0B0F14" },
  h3: { fontSize: 10, fontWeight: 700, marginTop: 8, marginBottom: 2 },
  body: { fontSize: 9.5, color: "#2C3E50", marginBottom: 4 },
  riskChip: { fontSize: 8, fontWeight: 700, marginBottom: 2 },
  citation: { fontSize: 8, color: "#148F66" },
  listItem: { fontSize: 8.5, color: "#2C3E50", marginBottom: 3 },
  footer: {
    position: "absolute",
    bottom: 24,
    left: 48,
    right: 48,
    flexDirection: "row",
    justifyContent: "space-between",
    fontSize: 7.5,
    color: "#95A5A6",
    borderTop: "1 solid #D5D8DC",
    paddingTop: 6,
  },
  noteBox: {
    backgroundColor: "#FDF2F0",
    padding: 8,
    marginTop: 4,
    marginBottom: 4,
    borderLeft: "2 solid #C0392B",
  },
  altBox: {
    backgroundColor: "#F0FAF6",
    padding: 8,
    marginTop: 4,
    marginBottom: 4,
    borderLeft: "2 solid #1E8449",
  },
});

function citationLabels(report: Report, ids: string[]): string {
  const labels = ids
    .map((id) => report.citations.find((c) => c.id === id)?.label)
    .filter(Boolean);
  return labels.length ? `[${labels.join("; ")}]` : "";
}

export function ReportPDF({ run }: { run: Run }) {
  const report = run.report!;
  const gis = run.gis!;

  return (
    <Document
      title={`GridSentry Assessment — ${gis.site.name}`}
      author="GridSentry"
    >
      <Page size="LETTER" style={styles.page}>
        <View style={styles.header}>
          <Text style={styles.brand}>GRIDSENTRY · ENVIRONMENTAL PERMIT INTELLIGENCE</Text>
          <Text style={styles.title}>{gis.site.name}</Text>
          <Text style={styles.meta}>
            {report.developable
              ? "Draft Environmental Impact Assessment"
              : "Site Eligibility Determination"}{" "}
            · {gis.site.lat.toFixed(4)}, {gis.site.lon.toFixed(4)} · {gis.site.acreage} acres ·{" "}
            {gis.site.project_type.toUpperCase()} · Generated{" "}
            {new Date(report.generated_at).toLocaleDateString()} ·{" "}
            {report.developable ? (
              <>
                Overall risk:{" "}
                <Text style={{ color: RISK_COLORS[report.risk_level], fontWeight: 700 }}>
                  {report.risk_level.toUpperCase()} ({report.risk_score}/100)
                </Text>
              </>
            ) : (
              <Text style={{ color: "#C0392B", fontWeight: 700 }}>
                VERDICT: NOT VIABLE —{" "}
                {report.land_status.category === "urban_built"
                  ? "NO BUILDABLE LAND (URBAN CORE)"
                  : report.land_status.category === "open_water"
                    ? "OPEN WATER"
                    : "FEDERAL PROTECTED LAND"}
              </Text>
            )}{" "}
            · Red-team confidence {report.confidence}%
          </Text>
          {!report.developable &&
            (report.land_status.category === "federal_protected" ? (
              <Text style={[styles.body, { color: "#C0392B", marginTop: 6, fontWeight: 700 }]}>
                Site falls within {report.land_status.unit_name} (
                {report.land_status.designation}, {report.land_status.manager}).
                {report.land_status.verified
                  ? " Verified against USGS PAD-US."
                  : " Flagged from offline reference — confirm against PAD-US."}
              </Text>
            ) : (
              <Text style={[styles.body, { color: "#C0392B", marginTop: 6, fontWeight: 700 }]}>
                The proposed {gis.site.acreage}-acre footprint sits on{" "}
                {report.land_status.category === "open_water"
                  ? "open water"
                  : "fully built-up urban land"}
                {report.land_status.land_cover_checked
                  ? ` (NLCD 2021: dominant cover ${report.land_status.dominant_cover}, ${Math.round(
                      (report.land_status.high_intensity_fraction ?? 0) * 100
                    )}% medium/high-intensity developed). Verified against USGS/MRLC NLCD.`
                  : ". Flagged from offline reference — confirm against NLCD."}
              </Text>
            ))}
        </View>

        <Text style={styles.h2}>Executive Summary</Text>
        <Text style={styles.body}>{report.executive_summary}</Text>

        {report.stop_work_risks.length > 0 && (
          <>
            <Text style={styles.h2}>Stop-Work Risks</Text>
            {report.stop_work_risks.map((r) => (
              <View key={r.id} style={styles.noteBox} wrap={false}>
                <Text style={[styles.h3, { color: "#C0392B", marginTop: 0 }]}>{r.title}</Text>
                <Text style={styles.body}>{r.detail}</Text>
                <Text style={[styles.listItem, { color: "#C0392B" }]}>
                  Trigger: {r.trigger} {citationLabels(report, r.citation_ids)}
                </Text>
              </View>
            ))}
          </>
        )}

        {report.sections.map((s) => (
          <View key={s.id}>
            <Text style={styles.h2}>{s.title}</Text>
            <Text style={[styles.riskChip, { color: RISK_COLORS[s.risk] }]}>
              SECTION RISK: {s.risk.toUpperCase()}
            </Text>
            <Text style={styles.body}>{s.summary}</Text>
            {s.findings.map((f) => (
              <View key={f.id} wrap={false} style={{ marginBottom: 4 }}>
                <Text style={styles.h3}>
                  <Text style={{ color: RISK_COLORS[f.severity] ?? "#566573" }}>● </Text>
                  {f.title}
                </Text>
                <Text style={styles.body}>
                  {f.detail}{" "}
                  <Text style={styles.citation}>
                    {citationLabels(report, f.citation_ids)}
                  </Text>
                </Text>
              </View>
            ))}
            {report.critic_notes
              .filter((n) => n.target === s.id)
              .map((n) => (
                <View key={n.id} style={styles.noteBox} wrap={false}>
                  <Text style={[styles.listItem, { color: "#C0392B", fontWeight: 700 }]}>
                    RED-TEAM {n.severity.toUpperCase()}
                  </Text>
                  <Text style={styles.listItem}>{n.note}</Text>
                </View>
              ))}
          </View>
        ))}

        {report.alternatives.length > 0 && (
          <>
            <Text style={styles.h2}>Recommended Alternatives</Text>
            {report.alternatives.map((a) => (
              <View key={a.id} style={styles.altBox} wrap={false}>
                <Text style={[styles.h3, { marginTop: 0 }]}>{a.title}</Text>
                <Text style={styles.body}>{a.description}</Text>
                <Text style={[styles.listItem, { color: "#1E8449" }]}>{a.impact_reduction}</Text>
              </View>
            ))}
          </>
        )}

        <Text style={styles.h2}>Sources & Citations</Text>
        {report.citations.map((c, i) => (
          <Text key={c.id} style={styles.listItem}>
            [{i + 1}] {c.label} — {c.title}. {c.source}.{" "}
            <Link src={c.url} style={styles.citation}>
              {c.url}
            </Link>
          </Text>
        ))}

        <Text style={styles.h2}>Data Sources</Text>
        {gis.sources.map((s) => (
          <Text key={s} style={styles.listItem}>
            • {s}
          </Text>
        ))}

        <View style={styles.footer} fixed>
          <Text>GridSentry — AI-generated draft. Not legal advice.</Text>
          <Text>CONFIDENTIAL — DEMO BUILD</Text>
          <Text
            render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`}
          />
        </View>
      </Page>
    </Document>
  );
}
