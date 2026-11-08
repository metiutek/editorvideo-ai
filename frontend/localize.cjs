// Traduce solo il testo dell'interfaccia: mai valori di API, file o input utente.
const chiavi = new Set()
const attributi = new Set(['title', 'placeholder', 'aria-label', 'alt', 'label', 'titolo', 'description'])

function testoJSX(value) {
  const righe = value.split(/\r\n|\n|\r/)
  let ultima = 0
  righe.forEach((r, i) => { if (/[^ \t]/.test(r)) ultima = i })
  return righe.map((r, i) => {
    let s = r.replace(/\t/g, ' ')
    if (i !== 0) s = s.replace(/^ +/, '')
    if (i !== righe.length-1) s = s.replace(/ +$/, '')
    return s && i !== ultima ? s+' ' : s
  }).join('')
}

module.exports = function localize({ types: t }) {
  function traduci(node, state) {
    if (t.isStringLiteral(node) && /[a-zA-Z]/.test(node.value) && !/^https?:\/\//.test(node.value)) {
      chiavi.add(node.value.trim())
      state.localizzato = true
      return t.callExpression(t.identifier('__uiT'), [t.stringLiteral(node.value)])
    }
    if (t.isConditionalExpression(node)) {
      node.consequent = traduci(node.consequent, state)
      node.alternate = traduci(node.alternate, state)
    }
    if (t.isBinaryExpression(node, { operator: '+' })) {
      node.left = traduci(node.left, state)
      node.right = traduci(node.right, state)
    }
    if (t.isTemplateLiteral(node)) {
      const key = node.quasis.map((q, i) => q.value.cooked + (i < node.expressions.length ? `{${i}}` : '')).join('')
      if (/[a-zA-Z]/.test(key)) {
        chiavi.add(key.trim())
        state.localizzato = true
        return t.callExpression(t.identifier('__uiT'), [t.stringLiteral(key), t.arrayExpression(node.expressions)])
      }
    }
    return node
  }
  return {
    visitor: {
      Program: {
        enter(path, state) { state.localizzato = false },
        exit(path, state) {
          if (state.localizzato) path.unshiftContainer('body', t.importDeclaration(
            [t.importSpecifier(t.identifier('__uiT'), t.identifier('translate'))], t.stringLiteral('./i18n.js')))
        },
      },
      JSXText(path, state) {
        const parent = path.parent.openingElement?.name?.name
        if (['code', 'pre', 'script', 'style'].includes(parent)) return
        const text = testoJSX(path.node.value)
        const node = traduci(t.stringLiteral(text), state)
        if (t.isCallExpression(node)) path.replaceWith(t.jsxExpressionContainer(node))
      },
      JSXAttribute(path, state) {
        if (!attributi.has(path.node.name.name)) return
        const v = path.node.value
        if (t.isStringLiteral(v)) path.node.value = t.jsxExpressionContainer(traduci(v, state))
        else if (t.isJSXExpressionContainer(v)) v.expression = traduci(v.expression, state)
      },
      JSXExpressionContainer(path, state) {
        if (path.parent.type === 'JSXAttribute') return
        if (['code', 'pre', 'script', 'style'].includes(path.parent.openingElement?.name?.name)) return
        path.node.expression = traduci(path.node.expression, state)
      },
    },
  }
}
module.exports.chiavi = chiavi
