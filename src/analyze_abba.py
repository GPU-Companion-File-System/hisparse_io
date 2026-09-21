#!/usr/bin/env python3
"""Validate an audited same-device ABBA run; report descriptive phase statistics."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

PHASES = ('A1', 'B1', 'B2', 'A2')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows):
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def stats(rows):
    latency = np.array([float(r['completion_us']) for r in rows])
    submit = np.array([float(r['submit_us']) for r in rows])
    n = int(rows[0]['n_reads'])
    if not np.all(np.isfinite(latency)) or not np.all(latency > 0):
        raise ValueError('Nonpositive/nonfinite completion latency')
    if not np.all(np.isfinite(submit)) or np.any(submit < 0):
        raise ValueError('Invalid submission time')
    q = np.percentile(latency, [50, 95, 99], method='linear')
    return dict(n_samples=len(rows), mean_us=float(latency.mean()), p50_us=float(q[0]),
                p95_us=float(q[1]), p99_us=float(q[2]), submit_mean_us=float(submit.mean()),
                max_us=float(latency.max()), rounds_over_100ms=int(np.sum(latency > 100000)),
                iops_mean=float(np.mean(n * 1e6 / latency)),
                iops_aggregate=float(n * len(rows) * 1e6 / latency.sum()),
                bandwidth_gbs_aggregate=float(n * len(rows) * 4096 / latency.sum() / 1000))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    meta = json.loads((run / 'workload.json').read_text())
    audit = json.loads((run / 'phase-audit.json').read_text())
    if audit['status'] != 'verified' or audit['data_sha256'] != meta['data_sha256']:
        raise ValueError('A verified phase and post-run data audit is required')
    if sha(run / 'trace.bin') != meta['trace_sha256']:
        raise ValueError('Trace changed')
    # Require exact trace record identity/order in every CSV, not just row counts.
    blob = (run / 'trace.bin').read_bytes()
    magic, io_size, slots, size, count, seed = struct.unpack_from('<8sIIQII', blob)
    if (magic, io_size, slots, size, count, seed) != (
        b'HSPTRC01', meta['io_size'], meta['hbm_slots'], meta['data_bytes'],
        meta['trace_records'], meta['seed']):
        raise ValueError('Trace header differs from workload metadata')
    expected = []
    offset = 32
    for _ in range(count):
        batch, ppm, n, phase, round_id = struct.unpack_from('<5I', blob, offset)
        expected.append((batch, ppm, n, phase, round_id))
        offset += 20 + 8 * n
    if offset != len(blob):
        raise ValueError('Trace length mismatch')
    groups = {}
    inputs = {}
    raw = []
    for phase in PHASES:
        path = run / f'raw-{phase}.csv'
        digest = sha(path)
        if digest != audit['phases'][phase]['raw_sha256']:
            raise ValueError(f'{phase}: CSV differs from audited file')
        rows = list(csv.DictReader(path.open()))
        identities = [(int(r['request_batch']), round(float(r['miss_rate']) * 1e6),
                       int(r['n_reads']), int(r['phase']), int(r['round'])) for r in rows]
        if identities != expected:
            raise ValueError(f'{phase}: CSV records differ from trace')
        backend = 'GDS' if phase.startswith('A') else 'Tutti-deployed'
        for row in rows:
            if row['backend'] != backend or row['correct'] != 'true' or row['error']:
                raise ValueError(f'{phase}: backend mismatch or data/IO failure')
            if (int(row['io_size']), int(row['queue_depth']), int(row['submission_group']),
                int(row['bytes_read'])) != (4096, 256, 16, int(row['n_reads']) * 4096):
                raise ValueError(f'{phase}: geometry mismatch')
            if int(row['phase']) == 1:
                key = (int(row['request_batch']), round(float(row['miss_rate']) * 1e6), int(row['n_reads']))
                groups.setdefault((phase, key), []).append(row)
            raw.append(dict(stage=phase, **row))
        inputs[phase] = dict(path=str(path), sha256=digest, rows=len(rows))
    keys = [tuple(k) for k in meta['configurations']]
    profile_run = meta.get('workload_kind') == 'hisparse_mean_derived_synthetic_nvme'
    detail = {(d['local_decode_batch'], round(d['reference_mean_miss_rate']*1e6), d['n_reads']): d
              for d in meta.get('configuration_details', [])}
    if set(groups) != {(p, k) for p in PHASES for k in keys}:
        raise ValueError('Missing or unexpected configurations')
    if any(len(rows) != meta['rounds_per_configuration'] for rows in groups.values()):
        raise ValueError('Incomplete measured samples')
    phase_stats = {(p, k): stats(groups[p, k]) for p in PHASES for k in keys}
    phase_rows = [dict(stage=p, request_batch=k[0], miss_rate=k[1]/1e6, n_reads=k[2],
                       **phase_stats[p, k]) for p in PHASES for k in keys]
    comparisons = []
    for k in keys:
        a = stats(groups['A1', k] + groups['A2', k])
        b = stats(groups['B1', k] + groups['B2', k])
        s = {p: phase_stats[p, k] for p in PHASES}
        comparisons.append(dict(request_batch=k[0], miss_rate=k[1]/1e6, n_reads=k[2],
            gds_p50_us=a['p50_us'], tutti_p50_us=b['p50_us'], p50_speedup=a['p50_us']/b['p50_us'],
            gds_p99_us=a['p99_us'], tutti_p99_us=b['p99_us'], p99_speedup=a['p99_us']/b['p99_us'],
            gds_iops=a['iops_aggregate'], tutti_iops=b['iops_aggregate'],
            iops_speedup=b['iops_aggregate']/a['iops_aggregate'],
            gds_submit_mean_us=a['submit_mean_us'], tutti_submit_mean_us=b['submit_mean_us'],
            a2_over_a1_p50=s['A2']['p50_us']/s['A1']['p50_us'],
            b2_over_b1_p50=s['B2']['p50_us']/s['B1']['p50_us'],
            a2_over_a1_p99=s['A2']['p99_us']/s['A1']['p99_us'],
            b2_over_b1_p99=s['B2']['p99_us']/s['B1']['p99_us']))
        if profile_run:
            comparisons[-1].update(scenario=detail[k]['scenario'],
                reference_gpu_cache_slots=detail[k]['gpu_cache_slots_per_request_per_layer'],
                effective_miss_rate=detail[k]['effective_miss_rate'])
    out = run / 'analysis'
    out.mkdir(exist_ok=False)
    write_csv(out / 'phase-summary.csv', phase_rows)
    write_csv(out / 'comparison.csv', comparisons)
    write_csv(out / 'all-rounds.csv', raw)
    styles = {'A1': ('#0072B2', 'o', '-'), 'A2': ('#0072B2', 's', '--'),
              'B1': ('#D55E00', '^', '-'), 'B2': ('#D55E00', 'v', '--')}
    facets = sorted({k[1] if profile_run else k[0] for k in keys})
    def points(facet):
        return sorted((k for k in keys if (k[1] if profile_run else k[0]) == facet),
                      key=lambda k: k[0] if profile_run else k[2])
    def xvalue(k):
        return k[0] if profile_run else k[2]
    def title(facet):
        if not profile_run:
            return f'request_batch = {facet}'
        d = detail[points(facet)[0]]
        return f"Reference miss = {facet/10000:g}%\n{d['reference_policy']}, {d['gpu_cache_slots_per_request_per_layer']} slots"
    xbase = 2 if profile_run else 10
    xlabel = 'Local decode batch (synthetic; log2)' if profile_run else '4 KiB reads per round (log10)'
    ncols = len(facets)
    measured_n = meta['rounds_per_configuration']
    with plt.rc_context({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42}):
        fig, axes = plt.subplots(2, ncols, figsize=(4*ncols, 7), layout='constrained', sharey='row', squeeze=False)
        for col, facet in enumerate(facets):
            kk = points(facet)
            for row, metric in enumerate(('p50_us', 'p99_us')):
                ax = axes[row, col]
                for p in ('A1', 'A2', 'B1', 'B2'):
                    color, marker, line = styles[p]
                    label = f'{p}: ' + ('GDS' if p.startswith('A') else 'Tutti')
                    ax.plot([xvalue(k) for k in kk], [phase_stats[p, k][metric]/1000 for k in kk],
                            color=color, marker=marker, linestyle=line, label=label)
                ax.set_xscale('log', base=xbase); ax.set_yscale('log', base=10)
                ax.set(title=title(facet), xlabel=xlabel)
                ax.grid(alpha=.2)
                if col == 0:
                    ax.set_ylabel(f'{metric[:3]} completion latency (ms; log10)')
        axes[0, -1].legend(fontsize=9)
        heading = 'HiSparse-derived synthetic NVMe reads (cache policies are reference labels)' if profile_run else 'Same SSD / GPU / trace'
        fig.suptitle(f'{heading}\nA1 → B1 → B2 → A2 · {measured_n} measured rounds/config/stage · all samples retained', fontsize=12)
        for ext in ('png', 'pdf'):
            fig.savefig(out / f'phase-latency.{ext}', dpi=200, facecolor='white')
        plt.close(fig)
        fig, axes = plt.subplots(1, ncols, figsize=(4*ncols, 3.8), layout='constrained', sharey=True, squeeze=False)
        axes = axes[0]
        for ax, facet in zip(axes, facets):
            kk = points(facet)
            for p in ('A1', 'A2', 'B1', 'B2'):
                color, marker, line = styles[p]
                ax.plot([xvalue(k) for k in kk], [phase_stats[p, k]['iops_aggregate']/1e6 for k in kk],
                        color=color, marker=marker, linestyle=line,
                        label=f'{p}: ' + ('GDS' if p.startswith('A') else 'Tutti'))
            ax.set_xscale('log', base=xbase)
            ax.set(title=title(facet), xlabel=xlabel)
            ax.grid(alpha=.2)
        axes[0].set_ylabel('Aggregate IOPS (million/s)')
        axes[0].set_ylim(0, max(s['iops_aggregate'] for s in phase_stats.values())/1e6*1.12)
        axes[-1].legend(fontsize=9)
        fig.suptitle(f'IOPS = total measured reads / total measured completion time\n{heading}', fontsize=11)
        for ext in ('png', 'pdf'):
            fig.savefig(out / f'phase-iops.{ext}', dpi=200, facecolor='white')
        plt.close(fig)
    report = ['# 同盘 GDS / Tutti A/B/B/A 结果', '',
        f"四阶段均完成；每阶段 {len(keys)} 配置 × {measured_n} 正式轮，并通过 {len(keys)*meta['warmups']} 轮预热与 {len(keys)*2} 次边界校验。",
        f"共 {4*len(keys)*measured_n} 条正式样本、{4*meta['trace_records']} 轮完整校验；未删除慢样本或失败样本。", '',
        '对象：cb 盘（`0000:cb:00.0`）与物理 GPU 0，同一 16 GiB 数据和 trace。',
        '完整证据在 `../phase-audit.json`；数据 SHA-256 在运行后再次验证。', '',
        '## 合并阶段的描述性比较', '',
        f'每后端每配置合并两阶段共 {2*measured_n} 轮。延迟加速比 = GDS/Tutti；大于 1 表示 Tutti 更快。',
        '这些轮次是重复测量，不是独立实验；无显著性或置信区间推断。', '',
        '| batch | miss | 读取数 | GDS p50 ms | Tutti p50 ms | p50 加速比 | p99 加速比 | IOPS 加速比 |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in comparisons:
        report.append(f"| {c['request_batch']} | {c['miss_rate']:.3f} | {c['n_reads']} | {c['gds_p50_us']/1000:.3f} | {c['tutti_p50_us']/1000:.3f} | {c['p50_speedup']:.2f} | {c['p99_speedup']:.2f} | {c['iops_speedup']:.2f} |")
    report += ['', '## 阶段漂移', '', '比值 = 后阶段/前阶段；1 为相同，超过 1 表示后阶段延迟更高。', '',
        '| batch | 读取数 | A2/A1 p50 | B2/B1 p50 | A2/A1 p99 | B2/B1 p99 |',
        '|---:|---:|---:|---:|---:|---:|']
    for c in comparisons:
        report.append(f"| {c['request_batch']} | {c['n_reads']} | {c['a2_over_a1_p50']:.3f} | {c['b2_over_b1_p50']:.3f} | {c['a2_over_a1_p99']:.3f} | {c['b2_over_b1_p99']:.3f} |")
    report += ['', '## 口径与限制', '',
        '- 主机观测整批完成延迟；16 个窗口，每窗口最多 16 IO，逻辑在途上限 256。',
        '- 相同 256 MiB 数据 HBM；Tutti 额外 PRP/队列元数据开销见客户端日志。',
        '- 描述符准备、初始化、HBM 预填和全量校验在计时外；Tutti 提交描述符搬运在计时内。',
        '- submit_us 是提交调用耗时之和，可与 IO 重叠，不能解释为独占 CPU 时间。',
        '- IOPS 采用总请求数/总计时完成时间；phase-summary.csv 另含每轮 IOPS 算术平均。',
        '- p99 为 numpy linear 百分位；每阶段仅 200 轮，尾部对少数慢样本敏感。',
        '- 阶段安排：' + audit['timing_caveat'],
        '- 工作负载：' + meta.get('mapping_assumption', '合成均匀随机 4 KiB 读；未执行真实模型、TopK 或 LRU。'),
        '- 共享 daemon 与本实验仅接管各自磁盘；没有修改或重载内核模块。',
        '- GDS 使用 CUDA 12.8/cuFile，Tutti 使用共享 CUDA 13；软件栈不同。',
        '- 这是当前适配器与固定提交策略的 IO 微基准；不等同最优后端或模型端到端性能。', '',
        f'![四阶段 p50/p99 完成延迟；横轴 log{xbase}，延迟纵轴 log10；不同标记区分阶段。](phase-latency.png)', '',
        '![四阶段吞吐量，按总请求数除以总完成时间计算；纵轴从零开始。](phase-iops.png)', '',
        '原始与汇总表：`all-rounds.csv`、`phase-summary.csv`、`comparison.csv`。']
    (out / 'REPORT.md').write_text('\n'.join(report)+'\n')
    provenance = dict(inputs=inputs, audit_sha256=sha(run/'phase-audit.json'),
        trace_sha256=meta['trace_sha256'], script_sha256=sha(Path(__file__)),
        numpy=np.__version__, matplotlib=matplotlib.__version__, excluded_measurement_rows=0,
        estimators='linear percentiles; aggregate IOPS; pooled backend samples; no inferential statistics',
        figure=dict(latency_inches=[4*ncols,7], latency_pixels=[800*ncols,1400],
                    iops_inches=[4*ncols,3.8], iops_pixels=[800*ncols,760], dpi=200, formats=['png','pdf'],
                    axes=f'log{xbase} x and log10 latency y, zero-based linear IOPS y; reject nonpositive latencies', uncertainty='none; separate observed stages',
                    destination='internal research report; no journal compliance claimed'))
    (out/'analysis.json').write_text(json.dumps(provenance,indent=2))
    print(out)
    print(json.dumps(comparisons,indent=2))


if __name__ == '__main__':
    main()
