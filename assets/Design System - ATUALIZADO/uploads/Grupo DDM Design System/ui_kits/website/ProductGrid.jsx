/* global React */
const PRODUCTS = [
  { name: 'RecuperEdu',         desc: 'Tenha uma cobrança de mensalidades atrasadas com eficiência e altas taxas de recuperação.', img: '../../assets/illustration-recovery.png' },
  { name: 'GesEdu',             desc: 'Ferramenta para controlar o fluxo de pagamentos da sua instituição.',                       img: '../../assets/illustration-payment.png' },
  { name: 'CreditEdu e InvesEdu', desc: 'Crédito para impulsionar o crescimento e desenvolvimento da sua instituição.',            img: '../../assets/illustration-laptop.png' },
  { name: 'Data Análise',       desc: 'Os dados necessários para sua instituição fidelizar e reter mais.',                          img: '../../assets/illustration-people.png' },
];

function ProductGrid({ onClick }) {
  return (
    <section className="ddm-products">
      <div className="ddm-products__head">
        <span className="ddm-eyebrow">Produtos exclusivos</span>
        <h2>Pensados para a jornada<br/>de crescimento da sua instituição.</h2>
      </div>
      <div className="ddm-products__grid">
        {PRODUCTS.map((p, i) => (
          <article className="ddm-product-card" key={i}>
            <img className="ddm-product-card__img" src={p.img} alt="" />
            <h3 className="ddm-product-card__name">{p.name}</h3>
            <p className="ddm-product-card__desc">{p.desc}</p>
            <button className="ddm-product-card__more" onClick={() => onClick && onClick(p.name)}>
              Ver mais
              <span className="ddm-product-card__arrow" aria-hidden="true">→</span>
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

window.ProductGrid = ProductGrid;
