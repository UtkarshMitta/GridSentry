import { renderToBuffer } from "@react-pdf/renderer";
import { NextResponse } from "next/server";
import { ReportPDF } from "@/lib/pdf-document";
import type { Run } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL =
  process.env.API_URL ??
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8000"
    : "https://gridsentry-api.onrender.com");

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const res = await fetch(`${API_URL}/runs/${params.id}`, { cache: "no-store" });
  if (!res.ok) {
    return NextResponse.json({ error: "Run not found" }, { status: 404 });
  }
  const run: Run = await res.json();
  if (run.status !== "complete" || !run.report || !run.gis) {
    return NextResponse.json(
      { error: "Report not ready yet" },
      { status: 409 },
    );
  }

  const buffer = await renderToBuffer(<ReportPDF run={run} />);
  const filename = `GridSentry_${run.gis.site.name.replace(/[^\w]+/g, "_")}.pdf`;

  return new NextResponse(new Uint8Array(buffer), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename="${filename}"`,
    },
  });
}
