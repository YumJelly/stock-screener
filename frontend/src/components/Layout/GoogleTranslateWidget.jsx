import { useState } from 'react';
import { IconButton, Menu, MenuItem, ListItemIcon, ListItemText } from '@mui/material';
import TranslateIcon from '@mui/icons-material/Translate';
import CheckIcon from '@mui/icons-material/Check';

const LANGUAGES = [
  { code: 'en',    label: 'English',   flag: '🇺🇸' },
  { code: 'zh-TW', label: '繁體中文',   flag: '🇹🇼' },
  { code: 'zh-CN', label: '简体中文',   flag: '🇨🇳' },
  { code: 'de',    label: 'Deutsch',    flag: '🇩🇪' },
];

function applyGoogleTranslate(langCode) {
  if (langCode === 'en') {
    // Remove translation cookies and reload to restore original
    document.cookie = 'googtrans=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    document.cookie = `googtrans=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; domain=${window.location.hostname}`;
    window.location.reload();
    return;
  }

  // Method 1: use Google's own doGTranslate helper (injected by the widget script)
  if (typeof window.doGTranslate === 'function') {
    window.doGTranslate(`en|${langCode}`);
    return;
  }

  // Method 2: programmatically change the hidden <select> the widget renders
  const select = document.querySelector('.goog-te-combo');
  if (select) {
    select.value = langCode;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }

  // Method 3: set googtrans cookie and reload (always works as fallback)
  document.cookie = `googtrans=/en/${langCode}; path=/`;
  document.cookie = `googtrans=/en/${langCode}; path=/; domain=${window.location.hostname}`;
  window.location.reload();
}

export default function GoogleTranslateWidget() {
  const [anchorEl, setAnchorEl] = useState(null);
  const [currentLang, setCurrentLang] = useState('en');

  const handleOpen = (event) => setAnchorEl(event.currentTarget);
  const handleClose = () => setAnchorEl(null);

  const handleSelect = (langCode) => {
    setCurrentLang(langCode);
    applyGoogleTranslate(langCode);
    handleClose();
  };

  return (
    <>
      <IconButton
        size="small"
        color="inherit"
        onClick={handleOpen}
        title="Translate page"
        sx={{ ml: 0.5 }}
      >
        <TranslateIcon fontSize="small" />
      </IconButton>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        {LANGUAGES.map((lang) => (
          <MenuItem
            key={lang.code}
            onClick={() => handleSelect(lang.code)}
            selected={lang.code === currentLang}
          >
            <ListItemIcon sx={{ minWidth: 32, fontSize: '16px' }}>
              {lang.flag}
            </ListItemIcon>
            <ListItemText>{lang.label}</ListItemText>
            {lang.code === currentLang && (
              <CheckIcon fontSize="small" sx={{ ml: 1, opacity: 0.7 }} />
            )}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
