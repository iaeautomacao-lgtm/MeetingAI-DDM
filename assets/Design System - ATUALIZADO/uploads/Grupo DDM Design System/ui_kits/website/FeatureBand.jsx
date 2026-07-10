/* global React */
const FEATURES = [
  { title: 'Maior satisfação dos seus alunos', desc: 'Plataforma de pagamento customizada com atendimento 24h por dia.', img: '../../assets/illustration-circle.png' },
  { title: 'Tenha um omnichannel real',         desc: 'Pode pagar por pix, boleto e cartão — pelo canal que o aluno preferir.', img: '../../assets/illustration-circle.png' },
  { title: 'Previsibilidade financeira',        desc: 'Tempo livre, apenas controle. Tecnologia de última ponta.',         img: '../../assets/illustration-circle.png' },
];

function FeatureBand() {
  return (
    <section className="ddm-features">
      <h2 className="ddm-features__title">
        Tenha seu setor financeiro mais <span className="scribble">sustentável</span>.
      </h2>
      <div className="ddm-features__grid">
        {FEATURES.map((f, i) => (
          <div className="ddm-feature" key={i}>
            <img src={f.img} alt="" className="ddm-feature__img" />
            <h3 className="ddm-feature__title">{f.title}</h3>
            <p className="ddm-feature__desc">{f.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

window.FeatureBand = FeatureBand;
