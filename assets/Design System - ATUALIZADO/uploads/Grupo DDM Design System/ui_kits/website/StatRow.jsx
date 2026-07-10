/* global React */
const STATS = [
  { num: 'Mais de 38%', desc: 'do Market Share educacional está conosco. Mais de 2.9 milhões de alunos contam com a DDM.' },
  { num: '897 milhões', desc: 'já negociado com alunos, ajudando-os a acharem boas condições financeiras para pagarem seus débitos.' },
  { num: '+ R$30MM', desc: 'garantidos em receitas antecipadas para nossas faculdades e colégios.' },
];

function StatRow() {
  return (
    <section className="ddm-stat-row">
      <div className="ddm-stat-row__title">
        <h2>Nós operacionalizamos,<br/><b>você controla.</b></h2>
        <p>O Grupo DDM elimina todos os atritos relacionados a pagamentos. Com dashboards interativos em tempo real, você tem na palma da mão sua operação e resultado sobre pagamentos dos seus alunos.</p>
      </div>
      <div className="ddm-stat-row__cards">
        {STATS.map((s, i) => (
          <div className="ddm-stat" key={i}>
            <div className="ddm-stat__num">{s.num}</div>
            <div className="ddm-stat__desc">{s.desc}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

window.StatRow = StatRow;
