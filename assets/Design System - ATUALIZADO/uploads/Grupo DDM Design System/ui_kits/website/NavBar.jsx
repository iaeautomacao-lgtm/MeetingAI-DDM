/* global React */
const { useState } = React;

function NavBar() {
  const [openMenu, setOpenMenu] = useState(null);
  return (
    <nav className="ddm-nav">
      <a href="#" className="ddm-nav__logo">
        <img src="../../assets/logo.png" alt="Grupo DDM" />
      </a>
      <ul className="ddm-nav__items">
        <li><a href="#">Quem somos</a></li>
        <li
          className="ddm-nav__has-dropdown"
          onMouseEnter={() => setOpenMenu('sol')}
          onMouseLeave={() => setOpenMenu(null)}
        >
          <a href="#">Soluções <span className="caret">▾</span></a>
          {openMenu === 'sol' && (
            <ul className="ddm-nav__dropdown">
              <li><a href="#">Recuperação de débitos</a></li>
              <li><a href="#">Serviços de crédito</a></li>
              <li><a href="#">Data Análise</a></li>
              <li><a href="#">Gesdu</a></li>
            </ul>
          )}
        </li>
        <li><a href="#">Contato</a></li>
        <li><a href="#">DDMacademy</a></li>
        <li><a href="#">Trabalhe conosco</a></li>
        <li><a href="#">Conformidade</a></li>
      </ul>
      <div className="ddm-nav__social">
        <a href="https://www.instagram.com/grupoddm/" aria-label="Instagram">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="0.8" fill="currentColor"/></svg>
        </a>
        <a href="https://www.linkedin.com/company/grupoddm/" aria-label="LinkedIn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM8.5 18H6V10h2.5v8zM7.2 8.9a1.4 1.4 0 1 1 0-2.8 1.4 1.4 0 0 1 0 2.8zM18.5 18H16v-4.2c0-1-.4-1.7-1.3-1.7s-1.5.6-1.5 1.7V18H10.7v-8h2.5v1.1c.4-.7 1.2-1.3 2.6-1.3 1.9 0 2.7 1.2 2.7 3.4V18z"/></svg>
        </a>
      </div>
    </nav>
  );
}

window.NavBar = NavBar;
