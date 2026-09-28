"""tcp_panel.py — painel "Placas do laboratório" da janela principal.

Desde 28/09/2026 o painel mostra uma linha por placa conhecida (placas.conf,
lista local e as que a varredura achar), com um ponto de cor e o que cada uma
está fazendo, pela porta de estado, atualizado a cada 4 s: livre, ocupada
(com qual operação e há quanto tempo), sem resposta ou com a FPGA não
preparada. A placa em uso é marcada; as outras têm um botão "Usar". Os campos
de endereço e porta ficam recolhidos em "Conexão manual".

Consome `morphe_theme` para estilos e helpers. A configuração TCP vive
na janela principal e é compartilhada por todas as janelas filhas
(FFT, Convolução, FIR). Estas chamam `master.tcp_panel.make_client()`
em vez de instanciar a própria.

Dois caminhos de conexão
────────────────────────
  - Conectar   : valida o servidor informado manualmente (host/porta/timeout)
                 com um handshake OP_PING e reporta hostname/FFT_N/Conv_N.
  - Autoconnect: varre a LAN e preenche host/porta com o primeiro servidor
                 Morphe encontrado.

Observação sobre o modelo de conexão
────────────────────────────────────
O protocolo Morphe é *sem conexão persistente*: cada operação (CONV/FFT/FIR)
abre um socket, envia, recebe e fecha (ver `TcpClient.request`). Por isso
"Conectar" aqui NÃO mantém um socket aberto — é uma verificação de
alcançabilidade/identidade do servidor (o mesmo OP_PING da descoberta),
para dar ao usuário confiança antes de abrir uma ferramenta. Também é por
isso que não há nada a "desconectar" ao fechar a GUI.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import List, Optional, Tuple

import morphe_theme as theme
from morphe_protocol import (
    TcpClient, ServerInfo, EstadoPlaca, consultar_estado, discover_servers,
    subredes_provaveis, build_ping_request, decode_ping_response,
)

# De quanto em quanto tempo o painel pergunta à placa conectada o que ela está
# fazendo (porta de estado, UDP: não entra na fila da placa).
ESTADO_INTERVALO_MS = 4000


# ======================================================================
# Placa lembrada — o mesmo arquivo que o morphe-up.sh escreve
# ======================================================================
# A versão 1.2 do plano tira do usuário a tarefa de saber o endereço da
# placa. O morphe-up.sh grava em .morphe-estado/placa a placa que acabou
# de preparar; o cliente lê dali e já abre conectado. Se o arquivo não
# existir (cliente em outra máquina, por exemplo), cai na busca pela LAN.


def _caminho_placa_lembrada() -> str:
    """<raiz do repositório>/.morphe-estado/placa — este módulo vive em Python/."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, ".morphe-estado", "placa")


def ler_placa_lembrada() -> Optional[str]:
    try:
        with open(_caminho_placa_lembrada(), encoding="utf-8") as f:
            ip = f.read().strip()
        return ip or None
    except OSError:
        return None


def _caminho_placas_conhecidas() -> str:
    """<raiz>/.morphe-estado/placas — todas as placas já preparadas."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, ".morphe-estado", "placas")


def _caminho_placas_laboratorio() -> str:
    """<raiz>/placas.conf — a lista versionada, igual em todo computador."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(raiz, "placas.conf")


def ler_placas_laboratorio() -> List[str]:
    """Os IPs do placas.conf: o primeiro campo de cada linha que não é
    comentário. Linha que não começa com um IPv4 é ignorada."""
    ips: List[str] = []
    try:
        with open(_caminho_placas_laboratorio(), encoding="utf-8") as f:
            for linha in f:
                campo = linha.split("#", 1)[0].split()
                if not campo:
                    continue
                partes = campo[0].split(".")
                if len(partes) == 4 and all(p.isdigit() and int(p) < 256 for p in partes):
                    ips.append(campo[0])
    except OSError:
        pass
    return ips


def ler_nomes_laboratorio() -> dict:
    """IP -> nome curto da placa, do comentário do placas.conf ("placa 1,
    de1soclinux, ..." vira "Placa 1"). Placa sem nome ali fica sem nome."""
    nomes: dict = {}
    try:
        with open(_caminho_placas_laboratorio(), encoding="utf-8") as f:
            for linha in f:
                util = linha.split("#", 1)[0].strip()
                if not util:
                    continue
                partes = util.split(None, 1)
                ip, resto = partes[0], (partes[1] if len(partes) > 1 else "")
                nome = resto.split(",", 1)[0].strip()
                if ip and nome:
                    nomes[ip] = nome[:1].upper() + nome[1:]
    except OSError:
        pass
    return nomes


def ler_placas_conhecidas() -> List[str]:
    """Todas as placas que este computador conhece, sem repetir.

    Três fontes, nesta ordem:
      - .morphe-estado/placas, que o morphe-up.sh acumula na máquina onde
        roda (a estação);
      - a placa "lembrada": num clone que só rodou antes desta lista
        existir, ela é a única que há;
      - placas.conf, versionado: é o que faz um computador recém-instalado
        achar as placas sem varrer a rede (desde 28/09/2026).
    """
    ips: List[str] = []
    try:
        with open(_caminho_placas_conhecidas(), encoding="utf-8") as f:
            ips = [l.strip() for l in f if l.strip()]
    except OSError:
        pass
    lembrada = ler_placa_lembrada()
    for ip in ([lembrada] if lembrada else []) + ler_placas_laboratorio():
        if ip not in ips:
            ips.append(ip)
    return ips


def acrescentar_placa_local(ip: str) -> bool:
    """Acrescenta ao .morphe-estado/placas uma placa achada pela varredura.
    Melhor esforço, como o gravar_placa_lembrada. True se acrescentou."""
    if ip in ler_placas_conhecidas():
        return False
    try:
        caminho = _caminho_placas_conhecidas()
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(ip + "\n")
        return True
    except OSError:
        return False


def gravar_placa_lembrada(ip: str) -> None:
    """Melhor esforço: um clone somente-leitura não é motivo para falhar."""
    try:
        caminho = _caminho_placa_lembrada()
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(ip)
    except OSError:
        pass


class TcpConfigPanel(ttk.LabelFrame):
    def __init__(self, parent,
                 default_host: str = "192.168.1.10",
                 default_port: int = 5000,
                 autoconectar: bool = False):
        # Garante que os estilos do tema existem mesmo se este painel
        # for instanciado fora do hub principal.
        theme.setup_styles(parent)

        super().__init__(
            parent,
            text=" Placas do laboratório ",
            style="Card.TLabelframe",
            padding=(18, 12, 18, 12),
        )

        # Threads de trabalho (autoconnect e conexão manual). Mantidas
        # separadas, mas mutuamente exclusivas via _busy().
        self._search_thread: Optional[threading.Thread] = None
        self._connect_thread: Optional[threading.Thread] = None
        self._cancel_event: Optional[threading.Event] = None
        self._success_handled = False

        # O que o painel sabe de cada placa: a lista (placas.conf e a local),
        # mais as que a varredura achar. Estado vem da porta de estado.
        conhecidas = ler_placas_conhecidas()
        self._ips: List[str] = list(conhecidas)
        self._nomes = ler_nomes_laboratorio()
        self._estados: dict = {}           # ip -> EstadoPlaca | None (sem resposta)
        self._consultadas: set = set()     # ips já consultados ao menos uma vez
        self._conectada: Optional[str] = None
        self._linhas: dict = {}            # ip -> widgets da linha
        self._estado_agendado = False

        # A placa preparada pelo morphe-up.sh tem precedência sobre o
        # default fixo -- que, no laboratório, nunca é o endereço certo.
        self.var_host = tk.StringVar(value=ler_placa_lembrada()
                                     or (conhecidas[0] if conhecidas else default_host))
        self.var_port = tk.StringVar(value=str(default_port))
        self.var_timeout = tk.StringVar(value="10")
        card = theme.COLORS["card_bg"]

        # --- resumo + "Procurar de novo" -------------------------------
        topo = ttk.Frame(self, style="Card.TFrame")
        topo.pack(fill="x")
        self.var_resumo = tk.StringVar(value="Procurando placas...")
        tk.Label(topo, textvariable=self.var_resumo, background=card,
                 foreground=theme.COLORS["text"], font=("TkDefaultFont", 10, "bold"),
                 anchor="w").pack(side="left")
        self.btn_autoconnect = ttk.Button(topo, text="Procurar de novo",
                                          style="Secondary.TButton",
                                          command=self._on_autoconnect)
        self.btn_autoconnect.pack(side="right")

        # --- uma linha por placa ---------------------------------------
        self._quadro_placas = tk.Frame(self, background=card)
        self._quadro_placas.pack(fill="x", pady=(8, 0))

        # --- mensagens (erros, placa achada fora da lista...) ----------
        self.var_status = tk.StringVar(value="")
        self.lbl_status = tk.Label(
            self, textvariable=self.var_status, background=card,
            foreground=theme.COLORS["info_fg"], font=("TkDefaultFont", 9),
            justify="left", anchor="w", wraplength=520,
        )
        self.lbl_status.pack(fill="x", pady=(6, 0))
        self.lbl_status.bind("<Configure>", lambda e: self.lbl_status.configure(
            wraplength=max(200, e.width - 8)))

        # --- conexão manual, recolhida ---------------------------------
        self._manual_aberta = False
        self._lbl_manual = tk.Label(self, background=card, cursor="hand2",
                                    foreground=theme.COLORS["text_muted"],
                                    font=("TkDefaultFont", 9), anchor="w")
        self._lbl_manual.pack(fill="x", pady=(6, 0))
        self._lbl_manual.bind("<Button-1>", lambda _e: self._alterna_manual())
        self._manual = ttk.Frame(self, style="Card.TFrame")
        self._manual.columnconfigure(1, weight=1)
        for linha, (rotulo, var) in enumerate((("Host", self.var_host),
                                               ("Porta", self.var_port),
                                               ("Timeout (s)", self.var_timeout))):
            ttk.Label(self._manual, text=rotulo, style="Card.TLabel").grid(
                row=linha, column=0, sticky="w", padx=(0, 10), pady=(0, 4))
            ttk.Entry(self._manual, textvariable=var).grid(
                row=linha, column=1, sticky="ew", pady=(0, 4))
        self.btn_connect = ttk.Button(self._manual, text="Conectar",
                                      style="Outline.TButton", command=self._on_connect)
        self.btn_connect.grid(row=3, column=1, sticky="e", pady=(2, 0))
        self._alterna_manual(inicial=True)

        self._desenha_placas()
        self._agenda_estado()

        if autoconectar:
            # Depois que a janela existe, para o status já ter onde aparecer.
            self.after(200, self._conectar_automaticamente)

    # ==================================================================
    # Conexão automática ao abrir (versão 1.2)
    # ==================================================================

    def _conectar_automaticamente(self):
        """Conecta sozinho, sem o usuário clicar em nada e sem diálogos.

        Tenta primeiro a placa lembrada — um handshake só, instantâneo — e
        só cai na varredura da LAN se ela não responder. Falhar aqui não é
        erro: o painel continua utilizável à mão, e quem está sem placa
        (gerador de sinais, comparação, projeto de FIR) não leva um pop-up
        na cara ao abrir o programa.
        """
        if self._busy():
            return

        lembrada = ler_placa_lembrada()
        try:
            porta = int(self.var_port.get())
        except ValueError:
            porta = 5000

        self._set_busy(True)
        self._mensagem("Escolhendo a placa...")
        self._cancel_event = threading.Event()
        self._success_handled = False

        conhecidas = ler_placas_conhecidas()

        def run():
            # As duas fontes, nesta ordem: primeiro a lista (placas.conf e a
            # local), que responde na hora; a varredura da rede vem depois, em
            # segundo plano, para achar placa que ficou fora da lista -- quase
            # sempre uma que trocou de IP por DHCP. Só sem nenhuma placa da
            # lista respondendo a varredura decide a conexão.
            escolha = None
            if len(conhecidas) > 1:
                escolha = self._escolher_placa_livre(conhecidas, porta)
            elif conhecidas:
                srv = self._sondar(conhecidas[0], porta)
                if srv is not None and srv.preparada:
                    escolha = (srv, 1, "")
            if escolha is not None:
                self.after(0, self._on_search_success, *escolha)
                threading.Thread(target=self._varrer_fora_da_lista,
                                 args=(conhecidas, escolha[0].ip, porta),
                                 daemon=True).start()
                return
            achados = self._varrer(lembrada or (conhecidas[0] if conhecidas else None),
                                   porta)
            escolha = self._escolher_entre(achados, porta)
            if escolha is not None:
                for a in achados:
                    acrescentar_placa_local(a.ip)
                self.after(0, self._acrescenta_placas, [a.ip for a in achados])
                self.after(0, self._on_search_success, *escolha)
            else:
                self.after(0, self._autoconexao_sem_placa, lembrada)

        self._search_thread = threading.Thread(target=run, daemon=True)
        self._search_thread.start()

    def _varrer(self, ip_referencia: Optional[str], porta: int) -> List[ServerInfo]:
        """Varre as sub-redes prováveis INTEIRAS (não para na primeira) e
        devolve as placas preparadas. Uns poucos segundos."""
        try:
            achados = discover_servers(
                subnets=subredes_provaveis(ip_referencia), port=porta,
                connect_timeout=0.3, read_timeout=0.5, max_workers=64,
                cancel_event=self._cancel_event, stop_on_first=False,
            )
        except Exception:
            achados = []
        return [a for a in achados if a.preparada]

    def _escolher_entre(self, achados: List[ServerInfo], porta: int
                        ) -> Optional[Tuple[ServerInfo, int, str]]:
        if not achados:
            return None
        if len(achados) == 1:
            return (achados[0], 1, "")
        return self._escolher_placa_livre([a.ip for a in achados], porta)

    def _varrer_fora_da_lista(self, conhecidas: List[str], perto_de: str, porta: int):
        """Depois de conectar pela lista: procura na rede placas que não estão
        nela. As que achar entram na lista local (valem a partir da próxima
        abertura) e o painel avisa para corrigir o placas.conf."""
        novas = [a.ip for a in self._varrer(perto_de, porta) if a.ip not in conhecidas]
        for ip in novas:
            acrescentar_placa_local(ip)
        if novas:
            try:
                self.after(0, self._avisa_placas_novas, novas)
            except RuntimeError:            # a janela fechou
                pass

    def _avisa_placas_novas(self, novas: List[str]):
        self._acrescenta_placas(novas)
        plural = len(novas) > 1
        self._mensagem(
            f"Achei na rede {'as placas' if plural else 'a placa'} {', '.join(novas)}, "
            "fora do placas.conf (o IP pode ter mudado). Já aparece"
            f"{'m' if plural else ''} acima e pode{'m' if plural else ''} ser "
            "usada; peça para corrigir o placas.conf.", "aviso")

    @classmethod
    def _escolher_placa_livre(cls, ips: List[str], porta: int
                              ) -> Optional[Tuple[ServerInfo, int, str]]:
        """Escolhe a placa para este computador. Devolve (placa, quantas
        responderam, uma linha sobre as outras) ou None.

        Com a porta de estado (servidor de 28/09/2026 em diante), cada placa
        diz na hora se está livre e quantos computadores a usaram no último
        minuto. Fica-se com a livre e menos usada: isso divide a turma entre
        as placas, em vez de todos caírem na que respondeu primeiro. Sem a
        porta de estado em nenhuma, vale o método antigo, abaixo.
        """
        import concurrent.futures as cf

        with cf.ThreadPoolExecutor(max_workers=max(2, len(ips))) as pool:
            estados = [e for e in pool.map(lambda ip: consultar_estado(ip, porta), ips)
                       if e is not None]
        candidatas = sorted((e for e in estados if e.preparada),
                            key=lambda e: (e.ocupada, e.clientes_recentes, e.rtt_s))
        for escolhida in candidatas:
            srv = cls._sondar(escolhida.ip, porta)
            if srv is not None and srv.preparada:
                outras = "; ".join(f"{e.ip}: {e.descricao()}"
                                   for e in estados if e.ip != escolhida.ip)
                return (srv, len(estados), outras)
        antigo = cls._escolher_pelo_ping(ips, porta)
        return None if antigo is None else (antigo[0], antigo[1], "")

    @classmethod
    def _escolher_pelo_ping(cls, ips: List[str], porta: int
                            ) -> Optional[Tuple[ServerInfo, int]]:
        """Método antigo: sonda todas em paralelo e devolve a que respondeu
        mais rápido.

        Por que o tempo do OP_PING mede ocupação: o servidor da placa é um
        laço accept/atende/fecha sem thread nenhuma, então um cliente no
        meio de uma convolução de ~200 ms segura o próximo na fila do
        listen(). Uma placa livre responde em milissegundos; uma ocupada
        responde depois de terminar o que está fazendo.

        Não é alocação de verdade — dois alunos que abram o cliente no
        mesmo instante ainda podem cair na mesma placa. Isso é a v1.4. O
        que isto resolve é o caso comum, e sem nenhum serviço novo.

        Devolve (placa escolhida, quantas responderam) ou None.
        """
        import concurrent.futures as cf

        def sondar_cronometrado(ip: str) -> Optional[Tuple[float, ServerInfo]]:
            t0 = time.monotonic()
            srv = cls._sondar(ip, porta)
            if srv is None:
                return None
            return (time.monotonic() - t0, srv)

        respostas: List[Tuple[float, ServerInfo]] = []
        with cf.ThreadPoolExecutor(max_workers=max(2, len(ips))) as pool:
            for r in pool.map(sondar_cronometrado, ips):
                if r is not None:
                    respostas.append(r)

        # Uma placa recém-ligada responde ao PING mas ainda tem o bitstream
        # de fábrica; escolhê-la travaria o HPS dela na primeira operação.
        respostas = [r for r in respostas if r[1].preparada]
        if not respostas:
            return None
        respostas.sort(key=lambda r: r[0])
        return (respostas[0][1], len(respostas))

    @staticmethod
    def _sondar(host: str, porta: int) -> Optional[ServerInfo]:
        """Um OP_PING contra um host conhecido. Devolve None em vez de levantar."""
        try:
            resp = TcpClient(host, porta, timeout=2.0).request(build_ping_request())
            return ServerInfo(ip=host, port=porta,
                              info=decode_ping_response(resp))
        except Exception:
            return None

    def _autoconexao_sem_placa(self, lembrada: Optional[str]):
        self._set_busy(False)
        self._mensagem("Nenhuma placa preparada respondeu. Quem prepara é o "
                       "./morphe-up.sh, na estação. As ferramentas que não precisam "
                       "de placa (gerador, comparador, projetistas) funcionam assim mesmo.",
                       "neutro")

    # ==================================================================
    # Guarda de exclusão mútua
    # ==================================================================

    def _busy(self) -> bool:
        """True se autoconnect OU conexão manual estiver em andamento."""
        for t in (self._search_thread, self._connect_thread):
            if t is not None and t.is_alive():
                return True
        return False

    # ==================================================================
    # Conexão manual: handshake OP_PING contra o host informado
    # ==================================================================

    def _on_connect(self):
        if self._busy():
            return

        # Validação síncrona dos campos (reusa make_client, que já checa
        # host/porta/timeout). Erros de campo não vão para a thread.
        try:
            client = self.make_client()
        except ValueError as e:
            messagebox.showerror("Configuração", str(e))
            return

        self._set_connect_busy(True)
        self._mensagem(f"Conectando a {client.host}:{client.port}...")

        def run():
            try:
                resp = client.request(build_ping_request())
                info = decode_ping_response(resp)  # valida service=morphe
                srv = ServerInfo(ip=client.host, port=client.port, info=info)
            except Exception as e:  # classificado no handler da thread Tk
                self.after(0, self._on_connect_error,
                           client.host, client.port, e)
                return
            self.after(0, self._on_connect_success, srv)

        self._connect_thread = threading.Thread(target=run, daemon=True)
        self._connect_thread.start()

    def _on_connect_success(self, srv: ServerInfo):
        self._set_connect_busy(False)
        gravar_placa_lembrada(srv.ip)
        self._marca_conectada(srv.ip)
        if srv.preparada:
            self._mensagem(f"{self._nome(srv.ip)}: conectado.", "ok")
        else:
            self._mensagem(f"{self._nome(srv.ip)} responde, mas a FPGA não foi "
                           "preparada: as operações serão recusadas até alguém rodar "
                           "./morphe-up.sh na estação.", "aviso")

    def _on_connect_error(self, host: str, port, e: Exception):
        self._set_connect_busy(False)
        self._mensagem(f"Falha ao conectar em {host}:{port}.", "erro")
        messagebox.showerror(
            "Conectar", self._describe_connect_error(host, port, e))

    @staticmethod
    def _describe_connect_error(host: str, port, e: Exception) -> str:
        """Traduz a exceção do handshake em mensagem acionável.

        A ordem dos testes importa: `socket.timeout` e
        `ConnectionRefusedError` são subclasses de `OSError`, então precisam
        vir antes do caso genérico.
        """
        if isinstance(e, (socket.timeout, TimeoutError)):
            return (f"Tempo esgotado ao conectar em {host}:{port}.\n\n"
                    "O host pode estar fora do ar, em outra rede, ou o "
                    "timeout é curto demais. Confira o IP e, se preciso, "
                    "aumente o timeout.")
        if isinstance(e, ConnectionRefusedError):
            return (f"Conexão recusada por {host}:{port}.\n\n"
                    "Existe um host nesse IP, mas nada escutando na porta — "
                    "o servidor Morphe provavelmente não está rodando, ou a "
                    "porta está errada.")
        if isinstance(e, RuntimeError):
            # Respondeu, porém com status de erro ou sem service=morphe.
            return (f"{host}:{port} respondeu, mas não se identificou como "
                    f"servidor Morphe.\n\nDetalhe: {e}")
        if isinstance(e, ValueError):
            # magic/opcode/versão inesperados em parse_response_header.
            return (f"{host}:{port} respondeu, mas fora do protocolo Morphe "
                    "(cabeçalho ou opcode inesperado). Provavelmente é outro "
                    "serviço nessa porta.")
        if isinstance(e, OSError):
            return (f"Não foi possível conectar em {host}:{port}.\n\n"
                    f"Detalhe: {e}")
        return f"Falha ao conectar em {host}:{port}.\n\nDetalhe: {e}"

    # ==================================================================
    # Autoconnect: fluxo plug-and-play em background
    # ==================================================================

    def _on_autoconnect(self):
        if self._busy():
            return

        # As duas fontes juntas: a lista (placas.conf e a local) e a varredura
        # completa das sub-redes prováveis -- a da placa lembrada primeiro, porque
        # as placas trocam de IP por DHCP. Escolhe entre todas as que responderem,
        # pela porta de estado, e não mais a primeira que a varredura achar.
        conhecidas = ler_placas_conhecidas()
        referencia = ler_placa_lembrada() or (conhecidas[0] if conhecidas else None)
        port = 5000  # constante do hardware

        self._set_busy(True)
        self._mensagem("Procurando placas na lista e na rede (alguns segundos)...")
        self._cancel_event = threading.Event()
        self._success_handled = False

        def run():
            achados = self._varrer(referencia, port)
            novas = [a.ip for a in achados if a.ip not in conhecidas]
            for ip in novas:
                acrescentar_placa_local(ip)
            todas = conhecidas + novas
            escolha = self._escolher_placa_livre(todas, port) if todas else None
            if escolha is not None:
                srv, quantas, outras = escolha
                if novas:
                    outras = (outras + "; " if outras else "") + \
                        f"fora do placas.conf: {', '.join(novas)}"
                self.after(0, self._on_search_success, srv, quantas, outras)
                if novas:
                    self.after(0, self._avisa_placas_novas, novas)
            elif self._cancel_event.is_set():
                self.after(0, self._on_search_cancelled)
            else:
                self.after(0, self._on_search_not_found)

        self._search_thread = threading.Thread(target=run, daemon=True)
        self._search_thread.start()

    def _on_search_success(self, srv: ServerInfo, entre: int = 1, outras: str = ""):
        if self._success_handled:
            return
        self._success_handled = True
        self.var_host.set(srv.ip)
        self.var_port.set(str(srv.port))
        # Escolha automática entre várias placas NÃO reescreve a placa
        # lembrada: ela é do morphe-up.sh, e sobrescrevê-la faria os
        # clientes se empurrarem de uma placa para a outra.
        if entre <= 1:
            gravar_placa_lembrada(srv.ip)
        self._set_busy(False)
        self._marca_conectada(srv.ip)
        motivo = (f"escolhida automaticamente: a mais livre de {entre}"
                  if entre > 1 else "conectado")
        self._mensagem(f"{self._nome(srv.ip)}: {motivo}.", "ok")

    # ==================================================================
    # As linhas de placa, atualizadas pela porta de estado
    # ==================================================================

    # (cor do ponto, texto curto) por situação
    _SITUACOES = {
        "livre":     ("#16a34a", "livre"),
        "ocupada":   ("#d97706", "ocupada"),
        "preparar":  ("#b91c1c", "FPGA não preparada"),
        "silencio":  ("#94a3b8", "sem resposta"),
        "consultando": ("#cbd5e1", "consultando..."),
    }

    def _nome(self, ip: str) -> str:
        if ip in self._nomes:
            return self._nomes[ip]
        e = self._estados.get(ip)
        return e.hostname if e is not None else ip

    def _situacao(self, ip: str) -> str:
        if ip not in self._consultadas:
            return "consultando"
        e = self._estados.get(ip)
        if e is None:
            return "silencio"
        if not e.preparada:
            return "preparar"
        return "ocupada" if e.ocupada else "livre"

    def _desenha_placas(self):
        """(Re)cria uma linha por placa conhecida. Só é chamada quando a lista
        de placas muda; o conteúdo das linhas muda em _atualiza_linhas."""
        card = theme.COLORS["card_bg"]
        for w in self._quadro_placas.winfo_children():
            w.destroy()
        self._linhas.clear()
        if not self._ips:
            tk.Label(self._quadro_placas, background=card,
                     foreground=theme.COLORS["text_muted"], anchor="w",
                     text="Nenhuma placa conhecida. Clique em “Procurar de novo”, "
                          "ou informe o endereço em “Conexão manual”.").pack(fill="x")
        for ip in self._ips:
            linha = tk.Frame(self._quadro_placas, background=card,
                             highlightthickness=1,
                             highlightbackground=theme.COLORS["border"])
            linha.pack(fill="x", pady=(0, 4))
            ponto = tk.Label(linha, text="●", background=card,
                             font=("TkDefaultFont", 14))
            ponto.pack(side="left", padx=(8, 6))
            acao = tk.Frame(linha, background=card, width=150)
            acao.pack(side="right", padx=8)
            textos = tk.Frame(linha, background=card)
            textos.pack(side="left", fill="x", expand=True, pady=4)
            titulo = tk.Label(textos, background=card, anchor="w",
                              foreground=theme.COLORS["text"],
                              font=("TkDefaultFont", 10, "bold"))
            titulo.pack(fill="x")
            detalhe = tk.Label(textos, background=card, anchor="w", justify="left",
                               foreground=theme.COLORS["text_muted"],
                               font=("TkDefaultFont", 9))
            detalhe.pack(fill="x")
            textos.bind("<Configure>", lambda e, d=detalhe: d.configure(
                wraplength=max(120, e.width - 4)))
            aqui = tk.Label(acao, text="✓ você está aqui", background=card,
                            foreground=theme.COLORS["ok_fg"],
                            font=("TkDefaultFont", 9, "bold"))
            usar = ttk.Button(acao, text="Usar", style="Outline.TButton",
                              command=lambda ip=ip: self._usar(ip))
            self._linhas[ip] = {"ponto": ponto, "titulo": titulo,
                                "detalhe": detalhe, "aqui": aqui, "usar": usar}
        self._atualiza_linhas()
        self._ajusta_altura()

    def _atualiza_linhas(self):
        livres = ocupadas = 0
        for ip, w in self._linhas.items():
            sit = self._situacao(ip)
            cor, curto = self._SITUACOES[sit]
            e = self._estados.get(ip)
            livres += sit == "livre"
            ocupadas += sit == "ocupada"
            w["ponto"].configure(foreground=cor)
            host = e.hostname if e is not None else ""
            nome = self._nome(ip)
            partes = [] if nome in (ip, host) else [nome]
            partes += [host] if host else []
            w["titulo"].configure(text="   ".join(partes + [ip]) if partes else ip)
            if sit in ("livre", "ocupada", "preparar"):
                detalhe = e.descricao()
            elif sit == "silencio":
                detalhe = ("sem resposta: desligada, fora da rede, ou com servidor "
                           "antigo (sem porta de estado)")
            else:
                detalhe = curto
            w["detalhe"].configure(text=detalhe)
            if ip == self._conectada:
                w["usar"].pack_forget()
                w["aqui"].pack()
            else:
                w["aqui"].pack_forget()
                w["usar"].pack()
                w["usar"].configure(state="disabled" if sit == "preparar" else "normal")
        n = len(self._linhas)
        if not n:
            self.var_resumo.set("Nenhuma placa")
        elif not self._consultadas:
            self.var_resumo.set(f"{n} placa{'s' if n > 1 else ''} · consultando...")
        else:
            partes = [f"{n} placa{'s' if n > 1 else ''}", f"{livres} livre{'s' if livres != 1 else ''}"]
            if ocupadas:
                partes.append(f"{ocupadas} ocupada{'s' if ocupadas > 1 else ''}")
            mudas = sum(self._situacao(ip) in ("silencio", "preparar") for ip in self._linhas)
            if mudas:
                partes.append(f"{mudas} indisponíve{'is' if mudas > 1 else 'l'}")
            self.var_resumo.set(" · ".join(partes))

    def _ajusta_altura(self):
        """Linha de placa nova depois de a janela abrir: a janela principal
        tem a altura medida no início e não cresceria sozinha."""
        topo = self.winfo_toplevel()
        topo.update_idletasks()
        h = topo.winfo_reqheight()
        if topo.winfo_ismapped() and topo.winfo_height() < h:
            topo.geometry(f"{topo.winfo_width()}x{h}")
            topo.minsize(topo.winfo_width(), h)

    def _acrescenta_placas(self, ips: List[str]):
        novas = [ip for ip in ips if ip not in self._ips]
        if novas:
            self._ips.extend(novas)
            self._desenha_placas()
            self._consulta(novas)

    def _marca_conectada(self, ip: str):
        self._conectada = ip
        self._acrescenta_placas([ip])
        self._atualiza_linhas()
        self._agenda_estado()

    def _usar(self, ip: str):
        """Botão "Usar" de uma linha: conecta àquela placa (handshake)."""
        if self._busy():
            return
        self.var_host.set(ip)
        self._on_connect()

    def _mensagem(self, texto: str, tipo: str = "info"):
        cores = {"info": "info_fg", "ok": "ok_fg", "aviso": "warn_fg",
                 "erro": "danger", "neutro": "text_muted"}
        self.var_status.set(texto)
        self.lbl_status.configure(foreground=theme.COLORS[cores[tipo]])

    def _alterna_manual(self, inicial: bool = False):
        if not inicial:
            self._manual_aberta = not self._manual_aberta
        if self._manual_aberta:
            self._manual.pack(fill="x", pady=(4, 0))
        else:
            self._manual.pack_forget()
        seta = "▾" if self._manual_aberta else "▸"
        self._lbl_manual.configure(text=f"{seta}  Conexão manual (endereço e porta)")
        if not inicial:
            self._ajusta_altura()

    def _agenda_estado(self):
        if not self._estado_agendado:
            self._estado_agendado = True
            self.after(100, self._atualiza_estado)

    def _atualiza_estado(self):
        """Consulta a porta de estado de todas as placas, em paralelo, numa
        thread (um UDP sem resposta leva meio segundo), e redesenha as linhas.
        Repete a cada ESTADO_INTERVALO_MS enquanto o painel existir."""
        if not self.winfo_exists():
            return
        self._consulta(list(self._ips))
        self.after(ESTADO_INTERVALO_MS, self._atualiza_estado)

    def _consulta(self, ips: List[str]):
        try:
            porta = int(self.var_port.get())
        except ValueError:
            porta = 5000

        def run():
            import concurrent.futures as cf
            with cf.ThreadPoolExecutor(max_workers=max(2, len(ips))) as pool:
                estados = dict(zip(ips, pool.map(lambda ip: consultar_estado(ip, porta), ips)))
            try:
                self.after(0, self._recebe_estados, estados)
            except RuntimeError:        # a janela fechou
                pass

        if ips:
            threading.Thread(target=run, daemon=True).start()

    def _recebe_estados(self, estados: dict):
        self._estados.update(estados)
        self._consultadas.update(estados)
        self._atualiza_linhas()

    def estado_placa(self, timeout: float = 0.5) -> Optional[EstadoPlaca]:
        """Para as janelas explicarem uma espera: o que a placa conectada está
        fazendo agora (None se ela não tem a porta de estado)."""
        try:
            return consultar_estado(self.var_host.get().strip(),
                                    int(self.var_port.get()), timeout)
        except ValueError:
            return None

    def _on_search_not_found(self):
        self._set_busy(False)
        self.var_status.set("")
        messagebox.showerror(
            "Procurar placas",
            "Nenhum servidor Morphe foi encontrado na rede local.\n\n"
            "Possíveis causas:\n"
            "- O servidor não está rodando no DE1-SoC\n"
            "- Cliente e servidor estão em redes diferentes\n"
            "- O servidor está em sub-rede fora de 101/102/103\n\n"
            "Verifique se o servidor está ativo no DE1-SoC e informe "
            "host e porta manualmente."
        )

    def _on_search_error(self, msg: str):
        self._set_busy(False)
        self.var_status.set("")
        messagebox.showerror("Procurar placas: erro", msg)

    def _on_search_cancelled(self):
        self._set_busy(False)
        self._mensagem("Busca cancelada.", "neutro")

    # ==================================================================
    # Estados de "ocupado" dos botões (ambos se desabilitam mutuamente)
    # ==================================================================

    def _buttons_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_connect.configure(state=state)
        self.btn_autoconnect.configure(state=state)

    def _set_busy(self, busy: bool):
        """Autoconnect em progresso: trava ambos, rotula o Autoconnect."""
        self._buttons_enabled(not busy)
        self.btn_autoconnect.configure(
            text="Procurando..." if busy else "Procurar de novo")
        if not busy:
            self.btn_connect.configure(text="Conectar")

    def _set_connect_busy(self, busy: bool):
        """Conexão manual em progresso: trava ambos, rotula o Conectar."""
        self._buttons_enabled(not busy)
        self.btn_connect.configure(
            text="Conectando..." if busy else "Conectar")
        if not busy:
            self.btn_autoconnect.configure(text="Procurar de novo")

    # ==================================================================
    # API pública usada pelas janelas filhas
    # ==================================================================

    def make_client(self):
        host = self.var_host.get().strip()
        try:
            port = int(self.var_port.get())
            timeout = float(self.var_timeout.get())
        except ValueError as e:
            raise ValueError("Porta e timeout devem ser numéricos") from e
        if not host:
            raise ValueError("Host vazio")
        return TcpClient(host, port, timeout=timeout)
