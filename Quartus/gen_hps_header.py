#!/usr/bin/env python3
"""gen_hps_header.py -- gera o C/hps_0.h a partir do soc_system.sopcinfo.

Substitui o `sopc-create-header-files` do SoC EDS, que so vem na instalacao
completa do Quartus (pasta `embedded/`) e nao no Quartus Prime Lite nem no
pacote Programmer standalone.

O `.sopcinfo` e XML puro e ja esta versionado no repositorio, entao este
script nao depende de Quartus nenhum -- roda com Python 3 limpo, em qualquer
maquina, inclusive Windows.

Uso:
    python gen_hps_header.py                 # gera ../C/hps_0.h
    python gen_hps_header.py --check         # so confere; nao escreve
    python gen_hps_header.py --stdout        # imprime na saida padrao

    python gen_hps_header.py --sopcinfo outro.sopcinfo --module hps_0 \
                            --output ../C/hps_0.h

Saida de --check: 0 se o cabeçalho no disco confere com o projeto de
hardware, 1 se divergir (util em CI ou como passo do script de preparacao
da versao 1.2).
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_SOPCINFO = os.path.join(HERE, "soc_system.sopcinfo")
DEFAULT_OUTPUT = os.path.join(HERE, os.pardir, "C", "hps_0.h")
DEFAULT_MODULE = "hps_0"


class Device:
    """Um slave mapeado em memoria, visto por um dos masters do HPS."""

    __slots__ = ("module", "slave", "base", "span", "kind", "master")

    def __init__(self, module, slave, base, span, kind, master):
        self.module = module
        self.slave = slave
        self.base = base
        self.span = span
        self.kind = kind
        self.master = master

    @property
    def prefix(self) -> str:
        return self.module.upper()

    @property
    def end(self) -> int:
        return self.base + self.span - 1


def collect(sopcinfo_path: str, module_name: str) -> tuple[list[Device], list[str]]:
    """Le o .sopcinfo e devolve (dispositivos, nomes dos masters)."""
    root = ET.parse(sopcinfo_path).getroot()

    # kind (classe do componente) de cada modulo do sistema
    kinds = {m.get("name"): m.get("kind") for m in root.iter("module")}

    target = None
    for m in root.iter("module"):
        if m.get("name") == module_name:
            target = m
            break
    if target is None:
        raise SystemExit(
            "erro: modulo '%s' nao encontrado em %s" % (module_name, sopcinfo_path)
        )

    devices: list[Device] = []
    masters: list[str] = []
    for iface in target.iter("interface"):
        blocks = iface.findall("memoryBlock")
        if not blocks:
            continue
        master = iface.get("name")
        masters.append(master)
        for b in blocks:
            devices.append(
                Device(
                    module=b.findtext("moduleName"),
                    slave=b.findtext("slaveName"),
                    base=int(b.findtext("baseAddress")),
                    span=int(b.findtext("span")),
                    kind=kinds.get(b.findtext("moduleName"), "unknown"),
                    master=master,
                )
            )

    # ordem estavel: por master (na ordem em que aparecem) e depois por endereco,
    # para que duas execucoes gerem exatamente o mesmo arquivo
    order = {name: i for i, name in enumerate(masters)}
    devices.sort(key=lambda d: (order[d.master], d.base))
    return devices, masters


def render(devices: list[Device], masters: list[str], sopcinfo_path: str,
           module_name: str) -> str:
    guard = "_ALTERA_%s_H_" % module_name.upper()
    out: list[str] = []
    w = out.append

    w("#ifndef %s" % guard)
    w("#define %s" % guard)
    w("")
    w("/*")
    w(" * ARQUIVO GERADO -- nao editar a mao.")
    w(" *")
    w(" * Gerado por Quartus/gen_hps_header.py a partir de")
    w(" * '%s', modulo '%s'." % (os.path.basename(sopcinfo_path), module_name))
    w(" *")
    w(" * Para regenerar, da pasta Quartus/:")
    w(" *     python gen_hps_header.py")
    w(" *")
    w(" * Substitui o 'sopc-create-header-files' do SoC EDS. Se o projeto de")
    w(" * hardware mudar, rode de novo -- 'python gen_hps_header.py --check'")
    w(" * acusa divergencia sem escrever nada.")
    w(" */")
    w("")
    w("/*")
    w(" * Dispositivos conectados aos masters:")
    for m in masters:
        w(" *   %s" % m)
    w(" */")
    w("")

    for d in devices:
        w("/*")
        w(" * Macros for device '%s', class '%s'" % (d.module, d.kind))
        w(" * The macros are prefixed with '%s_'." % d.prefix)
        w(" */")
        w("#define %s_COMPONENT_TYPE %s" % (d.prefix, d.kind))
        w("#define %s_COMPONENT_NAME %s" % (d.prefix, d.module))
        w("#define %s_BASE 0x%x" % (d.prefix, d.base))
        w("#define %s_SPAN %d" % (d.prefix, d.span))
        w("#define %s_END 0x%x" % (d.prefix, d.end))
        w("")

    w("#endif /* %s */" % guard)
    w("")
    return "\n".join(out)


def consistency_report(devices: list[Device]) -> list[str]:
    """Avisos sobre incoerencias entre o hardware e os limites do software.

    Le morphe_config.h se estiver acessivel, para nao duplicar constantes.
    """
    warnings: list[str] = []
    by_name = {d.module: d for d in devices}

    cfg_path = os.path.join(HERE, os.pardir, "C", "morphe_config.h")
    conv_n_max = None
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("#define MORPHE_CONV_N_MAX"):
                    try:
                        conv_n_max = int(line.split()[2])
                    except (IndexError, ValueError):
                        pass
    if conv_n_max is None:
        return warnings

    conv_y_max = 2 * conv_n_max - 1
    needed = conv_y_max * 4  # int32_t por amostra

    for name in ("conv1d_yn", "fir_yn"):
        dev = by_name.get(name)
        if dev is None:
            warnings.append("memoria '%s' ausente no projeto de hardware" % name)
            continue
        if dev.span < needed:
            warnings.append(
                "%s_SPAN = %d bytes (%d amostras) < MORPHE_CONV_Y_MAX = %d "
                "(%d bytes) -- o _Static_assert do servidor vai falhar"
                % (name.upper(), dev.span, dev.span // 4, conv_y_max, needed)
            )

    for name in ("conv1d_xn", "conv1d_hn", "fir_xn", "fir_hn"):
        dev = by_name.get(name)
        if dev is None:
            warnings.append("memoria '%s' ausente no projeto de hardware" % name)
        elif dev.span < conv_n_max * 4:
            warnings.append(
                "%s_SPAN = %d bytes (%d amostras) < MORPHE_CONV_N_MAX = %d"
                % (name.upper(), dev.span, dev.span // 4, conv_n_max)
            )

    return warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Gera o hps_0.h a partir do .sopcinfo, sem precisar do Quartus."
    )
    ap.add_argument("--sopcinfo", default=DEFAULT_SOPCINFO,
                    help="arquivo .sopcinfo (padrao: soc_system.sopcinfo ao lado deste script)")
    ap.add_argument("--module", default=DEFAULT_MODULE,
                    help="modulo cujos masters serao percorridos (padrao: hps_0)")
    ap.add_argument("--output", default=DEFAULT_OUTPUT,
                    help="destino (padrao: ../C/hps_0.h)")
    ap.add_argument("--check", action="store_true",
                    help="compara com o arquivo existente e sai com 1 se divergir")
    ap.add_argument("--stdout", action="store_true",
                    help="imprime o cabecalho na saida padrao em vez de gravar")
    args = ap.parse_args(argv)

    if not os.path.exists(args.sopcinfo):
        print("erro: nao encontrei %s" % args.sopcinfo, file=sys.stderr)
        print("      passe o caminho com --sopcinfo", file=sys.stderr)
        return 2

    devices, masters = collect(args.sopcinfo, args.module)
    text = render(devices, masters, args.sopcinfo, args.module)

    print("%d dispositivos em %d master(s): %s"
          % (len(devices), len(masters), ", ".join(masters)), file=sys.stderr)

    for warn in consistency_report(devices):
        print("AVISO: %s" % warn, file=sys.stderr)

    if args.stdout:
        sys.stdout.write(text)
        return 0

    if args.check:
        if not os.path.exists(args.output):
            print("check: %s nao existe" % args.output, file=sys.stderr)
            return 1
        with open(args.output, encoding="utf-8", errors="replace") as fh:
            atual = fh.read()
        if atual == text:
            print("check: %s confere com o projeto de hardware" % args.output,
                  file=sys.stderr)
            return 0
        print("check: %s DIVERGE do projeto de hardware -- regenere"
              % args.output, file=sys.stderr)
        return 1

    output = os.path.normpath(args.output)
    with open(output, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("gravado: %s" % output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
