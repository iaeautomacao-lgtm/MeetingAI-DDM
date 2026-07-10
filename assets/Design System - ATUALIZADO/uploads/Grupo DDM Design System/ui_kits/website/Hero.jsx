/* global React */
function Hero() {
  return (
    <section className="ddm-hero-section">
      <div className="ddm-hero-section__copy">
        <h1 className="ddm-hero-section__headline">
          Eficiência na <span className="scribble">Recuperação Financeira</span>
        </h1>
        <p className="ddm-hero-section__sub">
          Tecnologia financeira para instituições de ensino. Tenha seu setor financeiro mais sustentável: mais tempo para o que realmente importa — <b>educar.</b>
        </p>
        <div className="ddm-hero-section__ctas">
          <a className="ddm-btn" href="#">Sou instituição</a>
          <a className="ddm-btn ddm-btn--ghost" href="https://www.ddmpay.com.br/">Sou aluno</a>
        </div>
      </div>
      <div className="ddm-hero-section__media">
        <div className="ddm-photo-stack">
          <div className="ddm-photo-stack__squircle" />
          <img src="../../assets/hero-illustration.png" alt="Aluna usando o app DDMpay" />
        </div>
      </div>
    </section>
  );
}

window.Hero = Hero;
