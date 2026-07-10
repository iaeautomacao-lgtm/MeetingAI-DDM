/* global React */
function Footer() {
  return (
    <footer className="ddm-footer">
      <div className="ddm-footer__grid">
        <div className="ddm-footer__col">
          <img src="../../assets/logo.png" alt="Grupo DDM" className="ddm-footer__logo" />
          <h4>Endereço</h4>
          <p>Av. Ayrton Senna, Uptown.<br/>5500, Bl 2, terceiro andar.<br/>Barra da Tijuca, RJ.</p>
          <p className="ddm-footer__cnpj">
            GRUPO DDM COBRANÇA, CRÉDITO E CONTACT CENTER LTDA<br/>12.455.048/0001-73
          </p>
        </div>
        <div className="ddm-footer__col">
          <h4>Atendimento</h4>
          <p>Durante a semana, 09h às 19h.</p>
          <p>Telefone e WhatsApp <b>(21) 3030-9150</b></p>
          <p><a href="mailto:atendimento@ddm.adv.br">atendimento@ddm.adv.br</a></p>
          <p>Demais localidades <b>4020-7740</b></p>
          <p>Comercial: <b>(21) 99901-8751</b><br/><a href="mailto:comercial@grupoddm.com.br">comercial@grupoddm.com.br</a></p>
          <p><a href="mailto:marketing@grupoddm.com.br">marketing@grupoddm.com.br</a></p>
        </div>
        <div className="ddm-footer__col">
          <h4>LGPD</h4>
          <p>DPO: Roberta de Paiva Almeida</p>
          <p>Canal de privacidade: <a href="mailto:dpo@ddm.adv.br">dpo@ddm.adv.br</a></p>
          <p><a href="#">Política de privacidade</a></p>
          <p><a href="#">Compliance</a></p>
          <div className="ddm-footer__seals">
            <img src="../../assets/badge-lgpd.png" alt="LGPD" />
            <img src="../../assets/badge-esg.png" alt="ESG" />
          </div>
        </div>
      </div>
      <div className="ddm-footer__base">
        2024 © Copyright Grupo DDM. Todos os direitos reservados.
      </div>
    </footer>
  );
}

window.Footer = Footer;
