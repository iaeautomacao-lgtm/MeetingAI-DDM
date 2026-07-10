/* global React */
const { useState } = React;

function ContactForm({ onSubmit }) {
  const [type, setType] = useState('colegio');
  const [sent, setSent] = useState(false);
  return (
    <section className="ddm-contact">
      <div className="ddm-contact__head">
        <span className="ddm-eyebrow">Sua instituição junto das melhores</span>
        <h2>Entre em contato conosco e simule um início de operação.</h2>
      </div>
      <form
        className="ddm-contact__form"
        onSubmit={(e) => {
          e.preventDefault();
          setSent(true);
          onSubmit && onSubmit();
        }}
      >
        <div className="ddm-field">
          <label>Nome e sobrenome <span className="req">*</span></label>
          <input required placeholder="Seu nome completo" />
        </div>
        <div className="ddm-field">
          <label>Seu E-mail <span className="req">*</span></label>
          <input required type="email" placeholder="seu@email.com" />
        </div>
        <div className="ddm-field">
          <label>Seu celular</label>
          <input placeholder="(21) 99999-0000" />
        </div>
        <div className="ddm-field">
          <label>Nome da sua instituição</label>
          <input placeholder="Colégio Albert Einstein" />
        </div>
        <div className="ddm-field ddm-field--full">
          <label>Sua instituição é</label>
          <div className="ddm-radio-row">
            <label className={type === 'colegio' ? 'on' : ''}>
              <input type="radio" name="type" checked={type === 'colegio'} onChange={() => setType('colegio')} />
              <span className="dot" />Somos colégio
            </label>
            <label className={type === 'superior' ? 'on' : ''}>
              <input type="radio" name="type" checked={type === 'superior'} onChange={() => setType('superior')} />
              <span className="dot" />Somos ensino superior
            </label>
          </div>
        </div>
        <div className="ddm-field ddm-field--full">
          <button type="submit" className="ddm-btn">{sent ? 'Enviado ✓' : 'Enviar'}</button>
          {sent && <span className="ddm-contact__sent">Entraremos em contato em breve.</span>}
        </div>
      </form>
    </section>
  );
}

window.ContactForm = ContactForm;
