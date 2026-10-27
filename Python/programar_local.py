"""programar_local.py — o aplicativo programa a FPGA das placas ligadas neste PC.

Desde 22/10/2026, ao abrir, o aplicativo procura as placas ligadas pelo USB
(cabo JTAG) neste computador e grava nelas o bitstream do Morphe. Assim uma
placa pode trocar de computador e de ponto de rede no laboratório sem que
alguém precise ir à estação rodar o ./morphe-up.sh: basta abrir o aplicativo
no PC em que ela está ligada.

É o passo 3 do morphe-up.sh, e mais nada: o servidor da placa (que sobe
sozinho no boot) percebe a programação pela assinatura "MRPH" que o bitstream
põe no registrador GPI do FPGA manager, sem marca e sem ser reiniciado.

Regras, as mesmas do morphe-up.sh:
  - só Linux, e só se houver Quartus; sem ele, não faz nada e não reclama;
  - Quartus 20.1 de preferência (o que compilou o bitstream);
  - o cabo vem do jtagconfig, nunca de chute;
  - cabo com quartus_pgm aberto, de qualquer pasta ou conta, é pulado: aquela
    placa já foi programada e o tether da licença dela está vivo;
  - o quartus_pgm fica aberto em segundo plano depois de programar (o tether
    da licença do IP da FFT: quando ele morre, a FFT tem 1 hora), com o PGID
    em .morphe-estado/tethers/<cabo>.pid, onde o --status e o --down do
    morphe-up.sh o enxergam.

Limite conhecido: o tether é um processo da sessão de quem abriu o
aplicativo. Se o sistema encerra os processos no logout, ele morre junto, e a
FFT daquela placa passa a ter 1 hora; na próxima abertura do aplicativo, no
mesmo PC, a placa é programada de novo.
"""
from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOF = os.path.join(RAIZ, "Quartus", "output_files", "soc_system_time_limited.sof")
DIR_TETHERS = os.path.join(RAIZ, ".morphe-estado", "tethers")

# Dois aplicativos abertos ao mesmo tempo no mesmo PC (duas contas, ou dois
# cliques) não podem programar o mesmo cabo juntos. Até 27/10/2026 a trava era
# o arquivo /tmp/morphe-programar.lock; mas o Ubuntu (fs.protected_regular)
# não deixa uma conta abrir com O_CREAT um arquivo de outra no /tmp, mesmo
# 666, e a segunda conta a abrir o aplicativo desistia calada. Um soquete no
# espaço abstrato do Linux não tem arquivo nem dono: vale para todas as contas
# e some sozinho quando o processo termina.
TRAVA = "\0morphe-programar-fpga"

ESPERA_PROGRAMACAO_S = 60


@dataclass
class Resultado:
    cabo: str
    # "programada", "ja_programada" (tether vivo; detalhe = de quem), "falhou",
    # ou, sem cabo nenhum para tentar: "sem_quartus", "sem_cabo", "ocupado"
    # (outro aplicativo programando agora) e "nao_linux".
    situacao: str
    detalhe: str = ""


# ---------------------------------------------------------------------------
# Quartus
# ---------------------------------------------------------------------------

def _versao(bin_dir: str) -> str:
    try:
        saida = subprocess.run([os.path.join(bin_dir, "quartus_pgm"), "--version"],
                               capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"Version [0-9.]+", saida)
    return m.group(0) if m else ""


def achar_quartus() -> Optional[str]:
    """A pasta bin/ do Quartus, com quartus_pgm e jtagconfig, ou None. A
    20.1 ganha de qualquer outra; outra versão só sem 20.1, como no
    morphe-up.sh."""
    candidatos: List[str] = []
    no_path = shutil.which("quartus_pgm")
    if no_path:
        candidatos.append(os.path.dirname(no_path))
    casa = os.path.expanduser("~")
    bases = [os.environ.get("QUARTUS_ROOTDIR", "")]
    for padrao in ("/opt/intelFPGA_lite/20.1/quartus", f"{casa}/intelFPGA_lite/20.1/quartus",
                   "/opt/intelFPGA_lite/20.1/qprogrammer", f"{casa}/intelFPGA_lite/20.1/qprogrammer",
                   "/opt/intelFPGA_lite/*/quartus", f"{casa}/intelFPGA_lite/*/quartus",
                   "/opt/intelFPGA_lite/*/qprogrammer", f"{casa}/intelFPGA_lite/*/qprogrammer",
                   f"{casa}/intelFPGA/*/quartus"):
        bases += sorted(glob.glob(padrao))
    candidatos += [os.path.join(b, "bin") for b in bases if b]

    reserva = None
    vistos = set()
    for bin_dir in candidatos:
        if bin_dir in vistos:
            continue
        vistos.add(bin_dir)
        if not (os.access(os.path.join(bin_dir, "quartus_pgm"), os.X_OK)
                and os.access(os.path.join(bin_dir, "jtagconfig"), os.X_OK)):
            continue
        if _versao(bin_dir).startswith("Version 20.1"):
            return bin_dir
        reserva = reserva or bin_dir
    return reserva


def _ambiente(bin_dir: str) -> dict:
    env = dict(os.environ)
    env["QUARTUS_ROOTDIR"] = os.path.dirname(bin_dir)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


# ---------------------------------------------------------------------------
# Cabos
# ---------------------------------------------------------------------------

def ler_cabos(saida_jtagconfig: str) -> List[str]:
    """Os cabos DE-SoC na saída do jtagconfig ("1) DE-SoC [1-2]"). O
    jtagconfig desenha uma barra de progresso com \\r por cima da linha:
    cada \\r vira quebra de linha antes de procurar."""
    cabos = []
    for linha in saida_jtagconfig.replace("\r", "\n").splitlines():
        m = re.match(r"^\s*\d+\)\s+(.*\S)\s*$", linha)
        if m and "DE-SoC" in m.group(1):
            cabos.append(m.group(1))
    return cabos


def listar_cabos(bin_dir: str) -> List[str]:
    try:
        r = subprocess.run([os.path.join(bin_dir, "jtagconfig")], capture_output=True,
                           text=True, timeout=30, env=_ambiente(bin_dir))
    except (OSError, subprocess.SubprocessError):
        return []
    return ler_cabos(r.stdout + r.stderr)


def tethers_no_cabo(cabo: str) -> List[tuple]:
    """(pid, uid) de cada quartus_pgm aberto neste cabo, de qualquer conta.
    Lê o /proc, que mostra o nome e a linha de comando dos processos de todas
    as contas -- o mesmo que o 'pgrep -a quartus_pgm | grep cabo' do
    morphe-up.sh. O nome (comm), e não o primeiro argumento: o quartus_pgm do
    bin/ é um script, e o primeiro argumento pode ser o do interpretador."""
    achados = []
    for pasta in glob.glob("/proc/[0-9]*"):
        try:
            with open(os.path.join(pasta, "comm"), "rb") as f:
                if not f.read().startswith(b"quartus_pgm"):
                    continue
            with open(os.path.join(pasta, "cmdline"), "rb") as f:
                linha = f.read().replace(b"\0", b" ")
            uid = os.stat(pasta).st_uid
        except OSError:
            continue
        if cabo.encode() in linha:
            achados.append((int(os.path.basename(pasta)), uid))
    return achados


def cabo_em_uso(cabo: str) -> bool:
    return bool(tethers_no_cabo(cabo))


def _nome_conta(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)


def _derrubar_tethers_meus(tethers: List[tuple]) -> None:
    """Derruba o grupo (bash, sleep, quartus_pgm) de cada tether desta conta.
    Os de outra conta o sistema não deixa, e nem deve."""
    for pid, uid in tethers:
        if uid != os.getuid():
            continue
        try:
            os.killpg(os.getpgid(pid), 15)
        except OSError:
            pass
    for _ in range(10):                 # o quartus_pgm solta o cabo em ~1 s
        if not any(uid == os.getuid() for _p, uid in _ainda_vivos(tethers)):
            return
        time.sleep(0.5)


def _ainda_vivos(tethers: List[tuple]) -> List[tuple]:
    return [(p, u) for p, u in tethers if os.path.exists(f"/proc/{p}")]


def chave_cabo(cabo: str) -> str:
    """"DE-SoC [1-3]" vira "DE-SoC__1-3_", igual ao chave_cabo do morphe-up.sh."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", cabo)


# ---------------------------------------------------------------------------
# Programar
# ---------------------------------------------------------------------------

def _pasta_tethers() -> str:
    """A pasta do morphe-up.sh, 777 como lá (as contas dividem o clone). Num
    clone em que esta conta não escreve, uma pasta em /tmp: o --status do
    morphe-up.sh não a vê, mas o liberar_cabo dele acha o quartus_pgm pelo
    nome do cabo do mesmo jeito."""
    for pasta in (DIR_TETHERS,
                  os.path.join(tempfile.gettempdir(), f"morphe-tethers-{os.getuid()}")):
        try:
            os.makedirs(pasta, exist_ok=True)
            if pasta == DIR_TETHERS:
                for p in (os.path.dirname(pasta), pasta):
                    try:
                        os.chmod(p, 0o777)
                    except OSError:
                        pass
            if os.access(pasta, os.W_OK):
                return pasta
        except OSError:
            continue
    return tempfile.gettempdir()


def _grava(caminho: str, texto: str) -> None:
    """Apaga antes e deixa 666, como o grava_estado do morphe-up.sh."""
    try:
        os.remove(caminho)
    except OSError:
        pass
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    try:
        os.chmod(caminho, 0o666)
    except OSError:
        pass


def _erro_quartus(log: str) -> str:
    """A primeira linha "Error ..." do log, no formato do Quartus. Um
    'error' solto casaria com "0 errors" de uma programação que deu certo."""
    for linha in log.replace("\r", "\n").splitlines():
        if linha.startswith("Error"):
            return linha.strip()
    return ""


def programar_cabo(bin_dir: str, cabo: str) -> Resultado:
    pasta = _pasta_tethers()
    base = os.path.join(pasta, chave_cabo(cabo))
    arq_pid, arq_log = base + ".pid", base + ".log"
    _grava(arq_log, "")
    _grava(base + ".cabo", cabo)
    try:
        os.remove(arq_pid)
    except OSError:
        pass

    # O @2 é a posição da FPGA na cadeia JTAG; a 1 é o HPS. Sob setsid o bash
    # é líder de sessão: o $$ dele é o PGID do grupo (bash, sleep e
    # quartus_pgm), e é o que vai para o .pid. O 'sleep infinity |' mantém o
    # stdin do quartus_pgm aberto, e ele não sai: é o tether.
    script = (f"umask 000; echo $$ > {shlex.quote(arq_pid)}; "
              f"sleep infinity | quartus_pgm -m jtag -c {shlex.quote(cabo)} "
              f"-o {shlex.quote('p;' + SOF + '@2')} >> {shlex.quote(arq_log)} 2>&1")
    try:
        subprocess.Popen(["setsid", "bash", "-c", script], env=_ambiente(bin_dir),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        return Resultado(cabo, "falhou", f"não consegui abrir o quartus_pgm ({e})")

    limite = time.monotonic() + ESPERA_PROGRAMACAO_S
    while time.monotonic() < limite:
        time.sleep(1)
        try:
            with open(arq_log, encoding="utf-8", errors="replace") as f:
                log = f.read()
        except OSError:
            log = ""
        if "Configuration succeeded" in log:
            return Resultado(cabo, "programada")
        erro = _erro_quartus(log)
        if erro:
            _encerrar(arq_pid)
            return Resultado(cabo, "falhou", erro)
    _encerrar(arq_pid)
    return Resultado(cabo, "falhou", f"tempo esgotado; ver {arq_log}")


def _encerrar(arq_pid: str) -> None:
    """Derruba o grupo do tether que não programou."""
    try:
        with open(arq_pid, encoding="utf-8") as f:
            pgid = int(f.read().strip())
        os.killpg(pgid, 15)
    except (OSError, ValueError):
        pass


def programar_placas_locais(avisar: Callable[[str], None] = lambda _m: None,
                            forcar: bool = False) -> List[Resultado]:
    """Programa a FPGA de cada placa ligada pelo USB neste PC que ainda não
    tem tether. Com forcar (o botão "Gravar a FPGA"), também a que tem tether
    DESTA conta: ele é derrubado e a placa, gravada de novo; o de outra conta
    fica, e o resultado diz de quem é. Sem nada para tentar, devolve um só
    Resultado sem cabo, que diz por quê (sem_quartus, sem_cabo, ...). Nunca
    levanta."""
    if not sys.platform.startswith("linux"):
        return [Resultado("", "nao_linux")]
    if not os.path.isfile(SOF):
        return [Resultado("", "falhou", f"não achei o bitstream em {SOF}")]
    if shutil.which("setsid") is None:
        return [Resultado("", "falhou", "falta o comando setsid (pacote util-linux)")]
    trava = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            trava.bind(TRAVA)
        except OSError:
            return [Resultado("", "ocupado")]
        bin_dir = achar_quartus()
        if bin_dir is None:
            return [Resultado("", "sem_quartus")]
        cabos = listar_cabos(bin_dir)
        if not cabos:
            return [Resultado("", "sem_cabo")]
        resultados = []
        for cabo in cabos:
            tethers = tethers_no_cabo(cabo)
            if tethers and forcar:
                _derrubar_tethers_meus(tethers)
                tethers = tethers_no_cabo(cabo)
            if tethers:
                donos = sorted({_nome_conta(uid) for _pid, uid in tethers})
                resultados.append(Resultado(cabo, "ja_programada", ", ".join(donos)))
                continue
            avisar(f"Programando a FPGA da placa no cabo {cabo} (uns 10 s)...")
            resultados.append(programar_cabo(bin_dir, cabo))
        return resultados
    except Exception as e:          # o aplicativo abre de qualquer jeito
        return [Resultado("", "falhou", str(e))]
    finally:
        trava.close()


def descrever(r: Resultado) -> str:
    """Uma frase para quem está na frente do PC: o painel e o terminal dizem
    o mesmo."""
    if r.situacao == "programada":
        return f"FPGA gravada pelo cabo {r.cabo}, ligado neste PC."
    if r.situacao == "ja_programada":
        return (f"O cabo {r.cabo} já está com a FPGA gravada e a licença presa pela "
                f"conta {r.detalhe}. Para gravar de novo por esta conta, feche o Morphe "
                f"(ou rode ./morphe-up.sh --down) na conta {r.detalhe}.")
    if r.situacao == "sem_quartus":
        return ("Este PC não tem o Quartus (procurei em /opt/intelFPGA_lite e na pasta "
                "da conta): rode o instala-quartus.sh nele.")
    if r.situacao == "sem_cabo":
        return ("O jtagconfig não viu nenhuma placa no USB deste PC. Confira o cabo: é o "
                "mini-USB ao lado do botão de power, não o UART.")
    if r.situacao == "ocupado":
        return "Outro Morphe aberto neste PC está gravando a FPGA agora; espere uns 10 s."
    if r.situacao == "nao_linux":
        return "Gravar a FPGA pelo USB só funciona no Linux do laboratório."
    alvo = f"no cabo {r.cabo}" if r.cabo else "neste PC"
    return f"Não consegui gravar a FPGA {alvo}: {r.detalhe}"


if __name__ == "__main__":
    forcar = "--forcar" in sys.argv[1:]
    for r in programar_placas_locais(print, forcar=forcar):
        print(f"{r.cabo or '-'}: {r.situacao} {r.detalhe}".rstrip())
        print(f"  {descrever(r)}")
