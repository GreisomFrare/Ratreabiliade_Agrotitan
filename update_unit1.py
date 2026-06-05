import oracledb

uprinc = """uses
  Classes, Controls, Forms, StdCtrls, Buttons,
  DB, DBClient, uVsClientDataSet, SysUtils;

var
    btnRetornaEtapa: TButton;
    gFrmMotivo: TForm;
    gChk1, gChk2, gChk3, gChk4, gChk5, gChk6, gChk7: TCheckBox;
    gEdtObs: TEdit;
    gEstab, gNumero: Integer;
    gSerie: String;

procedure InserirHistorico(nEstab, nNumero: Integer; sSerie: String; nCodMotivo: Integer; sMotivoTexto: String);
var
    cdsHist: TVsClientDataSet;
    nNextId: Integer;
begin
    nNextId := dmConexao3c.QueryPegaCampo(
        'SEL_PESQUISAFILTRO',
        'GEN_APRVPEDCABHIST_IDAPRVPEDCA.NEXTVAL',
        ['?', '1:s', 'DUAL', '?', '2:s', '(0=0)'],
        [ftString, ftString],
        [10, 10]
    );
    cdsHist := TVsClientDataSet.Create(nil);
    try
        dmConexao3c.GetDspEdicaoParcialComChaves(
            cdsHist, 'APRVPEDCABHIST', '*', 'IDAPRVPEDCABHIST', [], False
        );
        cdsHist.OpenEmpty;
        cdsHist.Append;
        cdsHist.FieldByName('IDAPRVPEDCABHIST').AsInteger := nNextId;
        cdsHist.FieldByName('ESTAB').AsInteger            := nEstab;
        cdsHist.FieldByName('SERIE').AsString             := sSerie;
        cdsHist.FieldByName('NUMERO').AsInteger           := nNumero;
        cdsHist.FieldByName('USERID').AsString            := oDadosSis.UserId;
        cdsHist.FieldByName('DATA').AsDateTime            := Date;
        cdsHist.FieldByName('MOTIVO').AsString            := sMotivoTexto;
        cdsHist.FieldByName('ETAPA').AsInteger            := 1;
        cdsHist.FieldByName('CODMOTIVO').AsInteger        := nCodMotivo;
        cdsHist.Post;
        dmConexao3c.CDSApplyUpdates([cdsHist]);
    finally
        cdsHist.Free;
    end;
end;

procedure btnConfirmarClick(Sender);
var
    bInseriu: Boolean;
    cdsAux: TVsClientDataSet;
    sObs: String;
begin
    inherited(Sender, 'OnClick');
    if Trim(gEdtObs.Text) <> '' then
        sObs := Trim(gEdtObs.Text) + ' - '
    else
        sObs := '';

    bInseriu := False;
    if gChk1.Checked then begin InserirHistorico(gEstab, gNumero, gSerie,  8, sObs + 'Desconto para Aprovacao de Etapas'); bInseriu := True; end;
    if gChk2.Checked then begin InserirHistorico(gEstab, gNumero, gSerie,  9, sObs + 'Saldo negativo de item');             bInseriu := True; end;
    if gChk3.Checked then begin InserirHistorico(gEstab, gNumero, gSerie, 10, sObs + 'Participacao minima');                bInseriu := True; end;
    if gChk4.Checked then begin InserirHistorico(gEstab, gNumero, gSerie, 14, sObs + 'Margem minima');                     bInseriu := True; end;
    if gChk5.Checked then begin InserirHistorico(gEstab, gNumero, gSerie, 17, sObs + 'Valor minimo estabelecido');         bInseriu := True; end;
    if gChk6.Checked then begin InserirHistorico(gEstab, gNumero, gSerie, 20, sObs + 'Alteracao de comissao');             bInseriu := True; end;
    if gChk7.Checked then begin InserirHistorico(gEstab, gNumero, gSerie, 21, sObs + 'Grupo de itens');                   bInseriu := True; end;

    if not bInseriu then
    begin
        ShowMessage('Selecione ao menos um motivo.');
        Exit;
    end;

    cdsAux := TVsClientDataSet.Create(nil);
    try
        dmConexao3c.GetDspEdicaoParcial(
            cdsAux, 'PEDCAB', 'ETAPA,NUMERO,SERIE,ESTAB',
            ['NUMERO', gNumero, 'SERIE', gSerie, 'ESTAB', gEstab],
            True
        );
        if not cdsAux.IsEmpty then
        begin
            cdsAux.Edit;
            cdsAux.FieldByName('ETAPA').AsInteger := 1;
            cdsAux.Post;
            dmConexao3c.CDSApplyUpdates([cdsAux]);
        end;
    finally
        cdsAux.Free;
    end;

    gFrmMotivo.Close;
    ShowMessage('Pedido retornado para a Etapa Comercial.');
end;

procedure btnCancelarClick(Sender);
begin
    inherited(Sender, 'OnClick');
    gFrmMotivo.Close;
end;

procedure btnRetornaEtapaClick(Sender);
var
    lblTitulo, lblObs: TLabel;
    btnOK, btnCancel: TButton;
begin
    inherited(Sender, 'OnClick');
    gNumero := Trunc(FProcAnaliseFin.EB_NUMERO.Value);
    gSerie  := FProcAnaliseFin.EB_SERIE.Text;
    gEstab  := FProcAnaliseFin.EB_ESTAB.CodigoValue;
    if gNumero = 0 then
    begin
        ShowMessage('Nenhum pedido selecionado.');
        Exit;
    end;

    if gFrmMotivo <> nil then
    begin
        gFrmMotivo.Free;
        gFrmMotivo := nil;
    end;

    gFrmMotivo := TForm.Create(Application);
    gFrmMotivo.Caption := 'Retornar para Etapa Comercial';
    gFrmMotivo.Position := poScreenCenter;
    TControl(gFrmMotivo).Width  := 400;
    TControl(gFrmMotivo).Height := 360;

    lblTitulo := TLabel.Create(gFrmMotivo);
    TControl(lblTitulo).Parent := gFrmMotivo;
    TControl(lblTitulo).Left := 16;
    TControl(lblTitulo).Top  := 12;
    lblTitulo.Caption := 'Selecione os motivos para retornar para aprovacao comercial:';

    gChk1 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk1).Parent := gFrmMotivo;
    TControl(gChk1).Left := 16; TControl(gChk1).Top :=  36; TControl(gChk1).Width := 360;
    gChk1.Caption := 'Desconto para Aprovacao de Etapas';

    gChk2 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk2).Parent := gFrmMotivo;
    TControl(gChk2).Left := 16; TControl(gChk2).Top :=  60; TControl(gChk2).Width := 360;
    gChk2.Caption := 'Saldo negativo de item';

    gChk3 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk3).Parent := gFrmMotivo;
    TControl(gChk3).Left := 16; TControl(gChk3).Top :=  84; TControl(gChk3).Width := 360;
    gChk3.Caption := 'Participacao minima';

    gChk4 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk4).Parent := gFrmMotivo;
    TControl(gChk4).Left := 16; TControl(gChk4).Top := 108; TControl(gChk4).Width := 360;
    gChk4.Caption := 'Margem minima';

    gChk5 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk5).Parent := gFrmMotivo;
    TControl(gChk5).Left := 16; TControl(gChk5).Top := 132; TControl(gChk5).Width := 360;
    gChk5.Caption := 'Valor minimo estabelecido';

    gChk6 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk6).Parent := gFrmMotivo;
    TControl(gChk6).Left := 16; TControl(gChk6).Top := 156; TControl(gChk6).Width := 360;
    gChk6.Caption := 'Alteracao de comissao';

    gChk7 := TCheckBox.Create(gFrmMotivo);
    TControl(gChk7).Parent := gFrmMotivo;
    TControl(gChk7).Left := 16; TControl(gChk7).Top := 180; TControl(gChk7).Width := 360;
    gChk7.Caption := 'Grupo de itens';

    lblObs := TLabel.Create(gFrmMotivo);
    TControl(lblObs).Parent := gFrmMotivo;
    TControl(lblObs).Left := 16;
    TControl(lblObs).Top  := 210;
    lblObs.Caption := 'Observacao:';

    gEdtObs := TEdit.Create(gFrmMotivo);
    TControl(gEdtObs).Parent := gFrmMotivo;
    TControl(gEdtObs).Left   := 16;
    TControl(gEdtObs).Top    := 228;
    TControl(gEdtObs).Width  := 360;
    TControl(gEdtObs).Height := 22;
    gEdtObs.MaxLength := 360;

    btnOK := TButton.Create(gFrmMotivo);
    TControl(btnOK).Parent := gFrmMotivo;
    TControl(btnOK).Left   := 196; TControl(btnOK).Top    := 264;
    TControl(btnOK).Width  :=  90; TControl(btnOK).Height :=  28;
    btnOK.Caption := 'Confirmar';
    btnOK.OnClick := 'btnConfirmarClick';

    btnCancel := TButton.Create(gFrmMotivo);
    TControl(btnCancel).Parent := gFrmMotivo;
    TControl(btnCancel).Left   := 294; TControl(btnCancel).Top    := 264;
    TControl(btnCancel).Width  :=  90; TControl(btnCancel).Height :=  28;
    btnCancel.Caption := 'Cancelar';
    btnCancel.OnClick := 'btnCancelarClick';

    gFrmMotivo.Show;
end;

btnRetornaEtapa := TButton.Create(FProcAnaliseFin);
TWinControl(btnRetornaEtapa).Parent := FProcAnaliseFin.Panel1;
TControl(btnRetornaEtapa).Left   := 815;
TControl(btnRetornaEtapa).Top    := 108;
TControl(btnRetornaEtapa).Width  := 94;
TControl(btnRetornaEtapa).Height := 25;
btnRetornaEtapa.Caption := 'Retorna Etapa';
btnRetornaEtapa.OnClick := 'btnRetornaEtapaClick';"""

ssproj = """[Files]
File1=uPrinc.psc
Language1=0
FileCount=1
MainUnit=uPrinc"""

conn = oracledb.connect(user="VIASOFT", password="VIASOFT", dsn="NW596:30200/ORCL")
cur = conn.cursor()
cur.execute("UPDATE VSSCRIPTER SET CONTEUDO = :1 WHERE ID = 65", [uprinc])
cur.execute("UPDATE VSSCRIPTER SET CONTEUDO = :1 WHERE ID = 66", [ssproj])
conn.commit()
print("uPrinc (ID=65) e ssproj (ID=66) atualizados")
cur.close()
conn.close()
