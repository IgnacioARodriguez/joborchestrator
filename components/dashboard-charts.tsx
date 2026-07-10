"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  XAxis,
  YAxis,
} from "recharts"
import { MoreHorizontal } from "lucide-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { DECISION_LABELS } from "@/lib/types"
import type { JobPosting } from "@/lib/types"
import {
  decisionDistribution,
  pipelineFunnel,
  scoreHistogram,
  sourceDistribution,
  weeklyTrend,
} from "@/lib/stats"

const DECISION_COLORS: Record<string, string> = {
  APPLY_NOW: "var(--success)",
  APPLY_WITH_TAILORED_CV: "var(--info)",
  MAYBE: "var(--warning)",
  SKIP: "var(--neutral-muted-foreground)",
  AVOID: "var(--destructive)",
}

function ChartCard({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Card className="gap-4">
      <CardHeader className="grid-cols-[1fr_auto] gap-1 pb-0">
        <div>
          <CardTitle className="text-sm">{title}</CardTitle>
          <CardDescription className="text-xs">{description}</CardDescription>
        </div>
        <button
          type="button"
          aria-label={`${title} options`}
          className="flex size-8 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <MoreHorizontal className="size-4" />
        </button>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function DashboardCharts({ jobs }: { jobs: JobPosting[] }) {
  const decisions = decisionDistribution(jobs).map((d) => ({
    ...d,
    label: DECISION_LABELS[d.decision],
    fill: DECISION_COLORS[d.decision],
  }))
  const sources = sourceDistribution(jobs)
  const trend = weeklyTrend(jobs)
  const funnel = pipelineFunnel(jobs)
  const histogram = scoreHistogram(jobs)

  const barConfig = {
    count: { label: "Jobs", color: "var(--chart-1)" },
  } satisfies ChartConfig

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <ChartCard
        title="Decision distribution"
        description="How opportunities are ranked"
      >
        <ChartContainer config={barConfig} className="h-64 w-full">
          <BarChart accessibilityLayer data={decisions} margin={{ left: -12, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
              interval={0}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={[8, 8, 0, 0]} barSize={34}>
              {decisions.map((d) => (
                <Cell key={d.decision} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Opportunities by source"
        description="Where jobs are coming from"
      >
        <ChartContainer config={barConfig} className="h-64 w-full">
          <BarChart
            accessibilityLayer
            data={sources}
            layout="vertical"
            margin={{ left: 8, right: 16, top: 8 }}
          >
            <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="source"
              tickLine={false}
              axisLine={false}
              fontSize={11}
              width={72}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={[0, 8, 8, 0]} fill="var(--chart-1)" barSize={22}>
              {sources.map((source) => (
                <Cell
                  key={source.source}
                  fill={source.source.toLowerCase().includes("linkedin") ? "var(--chart-1)" : "var(--chart-2)"}
                  opacity={source.source.toLowerCase().includes("linkedin") ? 1 : 0.68}
                />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Weekly trend"
        description="New jobs found per day"
      >
        <ChartContainer config={barConfig} className="h-64 w-full">
          <LineChart accessibilityLayer data={trend} margin={{ left: -12, right: 16, top: 12 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              dataKey="count"
              type="monotone"
              stroke="var(--chart-1)"
              strokeWidth={2.25}
              dot={{ r: 3.5, fill: "var(--card)", stroke: "var(--chart-1)", strokeWidth: 2 }}
              activeDot={{ r: 5, fill: "var(--chart-1)", stroke: "var(--card)", strokeWidth: 2 }}
            />
          </LineChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Pipeline funnel"
        description="Progress from new to ready"
      >
        <ChartContainer config={barConfig} className="h-64 w-full">
          <BarChart
            accessibilityLayer
            data={funnel}
            layout="vertical"
            margin={{ left: 8, right: 16, top: 8 }}
          >
            <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="stage"
              tickLine={false}
              axisLine={false}
              fontSize={11}
              width={72}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={[0, 8, 8, 0]} fill="var(--chart-2)" barSize={22} />
          </BarChart>
        </ChartContainer>
      </ChartCard>

      <ChartCard
        title="Score distribution"
        description="Spread of ranking scores"
      >
        <ChartContainer config={barConfig} className="h-64 w-full">
          <BarChart accessibilityLayer data={histogram} margin={{ left: -12, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="range"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              fontSize={11}
              interval={0}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              fontSize={11}
              allowDecimals={false}
            />
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Bar dataKey="count" radius={[8, 8, 0, 0]} fill="var(--chart-3)" barSize={34} />
          </BarChart>
        </ChartContainer>
      </ChartCard>
    </div>
  )
}
